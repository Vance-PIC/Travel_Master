"""Persistence and provider adapter for the P1–P3 trip-planning flow."""

from __future__ import annotations

import concurrent.futures
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
import importlib.util
import os
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT, db_path, load_settings, save_settings
from src.db.database import get_connection
from src.planner.diagnostics import InstrumentedClient, event, operation, provider_call

_ROOT = PROJECT_ROOT.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_NAGOYA_DIR = _ROOT / "travel" / "nagoya"
_NAGOYA_LATEST_JSON = _NAGOYA_DIR / "flights" / "latest.json"
_NAGOYA_ITIN_CSV = _NAGOYA_DIR / "flights" / "itinerary_history.csv"
_NAGOYA_MONITOR_JSON = _NAGOYA_DIR / "flight-monitor.json"
_SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
_SERPAPI_ACCOUNT_URL = "https://serpapi.com/account.json"
_FSC_PREFIXES = {"CI", "BR", "JX", "CX", "JL", "NH", "KE", "OZ", "SQ", "TG"}


class PlannerError(ValueError):
    """A user-actionable planner/provider error."""


_scheduler_started = False
_scheduler_lock = threading.Lock()
_scheduler_stop = threading.Event()


@contextmanager
def _connection():
    conn = get_connection(db_path())
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS planner_search_cache ("
            "cache_key TEXT PRIMARY KEY, "
            "payload_json TEXT NOT NULL, "
            "cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS planner_p3_quote_runs ("
            "candidate_id TEXT PRIMARY KEY REFERENCES planner_candidates(id) ON DELETE CASCADE, "
            "traveler_signature TEXT NOT NULL, "
            "api_sources_json TEXT NOT NULL, "
            "status TEXT NOT NULL, "
            "message TEXT, "
            "checked_at TIMESTAMP NOT NULL)"
        )
        candidate_columns = {row["name"] for row in conn.execute("PRAGMA table_info(planner_candidates)")}
        if candidate_columns and "last_refresh_attempt_at" not in candidate_columns:
            conn.execute("ALTER TABLE planner_candidates ADD COLUMN last_refresh_attempt_at TIMESTAMP")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(planner_booking_quotes)")}
        if columns:
            for col_name, col_def in (
                ("api_source", "TEXT"),
                ("passenger_fares_json", "TEXT"),
                ("separate_tickets", "INTEGER NOT NULL DEFAULT 0"),
                ("verified_party_total", "INTEGER NOT NULL DEFAULT 0"),
                ("unverified_reason", "TEXT"),
                ("traveler_signature", "TEXT"),
            ):
                if col_name not in columns:
                    conn.execute(f"ALTER TABLE planner_booking_quotes ADD COLUMN {col_name} {col_def}")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _client():
    module_path = _ROOT / "mcp" / "ignav_client.py"
    spec = importlib.util.spec_from_file_location("travel_master_ignav_client", module_path)
    if not spec or not spec.loader:
        raise PlannerError("航班供應商模組無法載入，請檢查專案安裝狀態。")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    IgnavClient, IgnavError = module.IgnavClient, module.IgnavError
    client = IgnavClient()
    if not client.api_key:
        raise PlannerError("尚未設定 Ignav API 金鑰；請在伺服器環境設定 IGNAV_API_KEY。")
    return InstrumentedClient(client), IgnavError


def _get_serpapi_key() -> str | None:
    """Resolve SERPAPI_KEY from .env, os.environ, or Windows Registry."""
    key_names = ["SERPAPI_KEY", "SERPAPI_API_KEY", "serpapi_key"]
    try:
        from mcp.ignav_client import _read_env_file, _read_windows_registry
        env_vars = _read_env_file()
        for name in key_names:
            if env_vars.get(name):
                return env_vars[name]
        for name in key_names:
            val = os.environ.get(name)
            if val and val.strip():
                return val.strip()
        for name in key_names:
            val = _read_windows_registry(name)
            if val:
                return val
    except Exception:
        for name in key_names:
            val = os.environ.get(name)
            if val and val.strip():
                return val.strip()
    return None


def _serpapi_request(params: dict[str, Any], endpoint: str = _SERPAPI_SEARCH_URL, timeout: int = 25) -> dict[str, Any]:
    if endpoint == _SERPAPI_SEARCH_URL and params.get("engine") == "google_flights":
        # Local freshness cache is handled before this call; live requests bypass provider cache.
        params = {**params, "no_cache": "true"}
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "TravelMaster-Planner/2.0",
        },
    )
    def invoke():
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    return provider_call("serpapi", endpoint, params, invoke)



def _load_json(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


AIRPORTS_DB: list[dict[str, str]] = [
    {"iata": "TPE", "city": "台北", "name": "桃園國際機場 (Taiwan Taoyuan)", "country": "台灣", "keywords": "台北 桃園 台灣 tpe taipei taoyuan"},
    {"iata": "TSA", "city": "台北", "name": "台北松山機場 (Taipei Songshan)", "country": "台灣", "keywords": "台北 松山 台灣 tsa songshan"},
    {"iata": "KHH", "city": "高雄", "name": "小港國際機場 (Kaohsiung)", "country": "台灣", "keywords": "高雄 小港 台灣 khh kaohsiung"},
    {"iata": "RMQ", "city": "台中", "name": "清泉崗機場 (Taichung)", "country": "台灣", "keywords": "台中 清泉崗 台灣 rmq taichung"},
    {"iata": "NGO", "city": "名古屋", "name": "中部國際機場 (Chubu Centrair)", "country": "日本", "keywords": "名古屋 中部 ngo chubu centrair nagoya"},
    {"iata": "KIX", "city": "大阪", "name": "關西國際機場 (Kansai)", "country": "日本", "keywords": "大阪 關西 京都 kix kansai osaka"},
    {"iata": "ITM", "city": "大阪", "name": "伊丹機場 (Osaka Itami)", "country": "日本", "keywords": "大阪 伊丹 itm itami osaka"},
    {"iata": "HND", "city": "東京", "name": "東京羽田國際機場 (Haneda)", "country": "日本", "keywords": "東京 羽田 hnd tokyo haneda"},
    {"iata": "NRT", "city": "東京", "name": "東京成田國際機場 (Narita)", "country": "日本", "keywords": "東京 成田 nrt tokyo narita"},
    {"iata": "FUK", "city": "福岡", "name": "福岡機場 (Fukuoka)", "country": "日本", "keywords": "福岡 九州 fuk fukuoka"},
    {"iata": "OKA", "city": "沖繩", "name": "那霸機場 (Okinawa Naha)", "country": "日本", "keywords": "沖繩 那霸 oka okinawa naha"},
    {"iata": "KMJ", "city": "熊本", "name": "阿蘇熊本機場 (Aso Kumamoto)", "country": "日本", "keywords": "熊本 阿蘇 九州 kmj kumamoto aso"},
    {"iata": "CTS", "city": "札幌", "name": "新千歲機場 (New Chitose)", "country": "日本", "keywords": "札幌 新千歲 北海道 cts sapporo chitose hokkaido"},
    {"iata": "KOJ", "city": "鹿兒島", "name": "鹿兒島機場 (Kagoshima)", "country": "日本", "keywords": "鹿兒島 九州 koj kagoshima"},
    {"iata": "MYJ", "city": "松山", "name": "四國松山機場 (Matsuyama)", "country": "日本", "keywords": "松山 四國 myj matsuyama"},
    {"iata": "TAK", "city": "高松", "name": "高松機場 (Takamatsu)", "country": "日本", "keywords": "高松 四國 tak takamatsu"},
    {"iata": "SDJ", "city": "仙台", "name": "仙台機場 (Sendai)", "country": "日本", "keywords": "仙台 東北 sdj sendai"},
    {"iata": "AOJ", "city": "青森", "name": "青森機場 (Aomori)", "country": "日本", "keywords": "青森 東北 aoj aomori"},
    {"iata": "HKD", "city": "函館", "name": "函館機場 (Hakodate)", "country": "日本", "keywords": "函館 北海道 hkd hakodate"},
    {"iata": "OKJ", "city": "岡山", "name": "岡山桃太郎機場 (Okayama)", "country": "日本", "keywords": "岡山 桃太郎 okj okayama"},
    {"iata": "HIJ", "city": "廣島", "name": "廣島機場 (Hiroshima)", "country": "日本", "keywords": "廣島 hij hiroshima"},
    {"iata": "ICN", "city": "首爾", "name": "仁川國際機場 (Incheon)", "country": "韓國", "keywords": "首爾 仁川 韓國 icn incheon seoul"},
    {"iata": "GMP", "city": "首爾", "name": "金浦國際機場 (Gimpo)", "country": "韓國", "keywords": "首爾 金浦 韓國 gmp gimpo seoul"},
    {"iata": "PUS", "city": "釜山", "name": "金海國際機場 (Gimhae)", "country": "韓國", "keywords": "釜山 金海 韓國 pus busan"},
    {"iata": "BKK", "city": "曼谷", "name": "蘇凡納布機場 (Suvarnabhumi)", "country": "泰國", "keywords": "曼谷 泰國 bkk bangkok"},
    {"iata": "DMK", "city": "曼谷", "name": "廊曼國際機場 (Don Mueang)", "country": "泰國", "keywords": "曼谷 廊曼 泰國 dmk"},
    {"iata": "SIN", "city": "新加坡", "name": "樟宜國際機場 (Changi)", "country": "新加坡", "keywords": "新加坡 樟宜 sin singapore changi"},
    {"iata": "HKG", "city": "香港", "name": "香港國際機場 (Hong Kong)", "country": "香港", "keywords": "香港 赤鱲角 hkg hong kong"},
    {"iata": "DAD", "city": "峴港", "name": "峴港國際機場 (Da Nang)", "country": "越南", "keywords": "峴港 越南 dad da nang"},
]


def _airport_code(value: str) -> str:
    clean = (value or "").strip()
    if not clean:
        raise PlannerError("請輸入或選擇機場（支援中文城市、機場名稱或三碼 IATA 代碼）。")
    # 1. Check parenthesized IATA like "台北桃園 (TPE)"
    paren = re.search(r"\(([A-Za-z]{3})\)", clean)
    if paren:
        return paren.group(1).upper()
    # 2. Exact 3-letter IATA code
    if re.fullmatch(r"[A-Za-z]{3}", clean):
        return clean.upper()
    # 3. Trailing/isolated 3-letter IATA token like "桃園 TPE"
    word = re.search(r"(?:^|\s)([A-Za-z]{3})(?:\s|$)", clean)
    if word:
        candidate = word.group(1).upper()
        if any(a["iata"] == candidate for a in AIRPORTS_DB):
            return candidate
    # 4. Fuzzy match against AIRPORTS_DB (Chinese city/name/keywords)
    lower = clean.lower()
    for a in AIRPORTS_DB:
        if (
            a["iata"].lower() == lower
            or a["city"].lower() == lower
            or lower in a["city"].lower()
            or a["city"].lower() in lower
            or lower in a["name"].lower()
            or lower in a["keywords"].lower()
        ):
            return a["iata"]
    raise PlannerError("請從機場搜尋結果選擇機場，或輸入三碼 IATA 機場代碼。")


def _dates(start: str, end: str) -> list[str]:
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError) as exc:
        raise PlannerError("請填寫有效的日期。") from exc
    if last < first:
        raise PlannerError("日期區間的結束日不可早於開始日。")
    if (last - first).days > 13:
        raise PlannerError("單次日期區間最多 14 天，避免一次送出過多供應商查詢。")
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def _traveler_counts(travelers: dict[str, Any]) -> tuple[int, int, bool]:
    adults = int(travelers.get("adults", 0))
    children = travelers.get("children", [])
    if adults < 1 or adults > 9 or not isinstance(children, list) or adults + len(children) > 9:
        raise PlannerError("旅客需至少 1 位成人，總人數不可超過 9 位。")
    ages: list[int] = []
    for child in children:
        age = child.get("age_at_departure") if isinstance(child, dict) else child
        if isinstance(age, bool) or not isinstance(age, int) or age < 0 or age > 17:
            raise PlannerError("兒童出發時年齡需為 0 至 17 歲。")
        ages.append(age)
    # Ignav classifies ages 12+ as adults, ages 2–11 as children. A lap/seat
    # choice is needed for under-2 travelers, which the approved UI schema lacks.
    provider_adults = adults + sum(age >= 12 for age in ages)
    provider_children = sum(2 <= age <= 11 for age in ages)
    has_infant = any(age < 2 for age in ages)
    return provider_adults, provider_children, has_infant


AIRLINE_NAMES_ZH: dict[str, str] = {
    "CI": "中華航空",
    "BR": "長榮航空",
    "JX": "星宇航空",
    "IT": "台灣虎航",
    "JL": "日本航空",
    "NH": "全日空",
    "CX": "國泰航空",
    "MM": "樂桃航空",
    "TR": "酷航",
    "D7": "全亞航 X",
    "FD": "泰亞航",
    "KE": "大韓航空",
    "OZ": "韓亞航空",
    "BX": "釜山航空",
    "TW": "德威航空",
    "GK": "捷星日本",
    "SL": "泰獅航",
    "VZ": "泰越捷航空",
}

FX_TO_TWD: dict[str, float] = {
    "TWD": 1.0,
    "USD": 31.75,
    "JPY": 0.21,
    "KRW": 0.023,
    "HKD": 4.08,
    "SGD": 23.8,
    "THB": 0.92,
}


def _to_twd(amount: float | None, currency: str | None) -> tuple[float | None, str | None]:
    if amount is None or amount <= 0:
        return None, None
    cur = str(currency or "TWD").strip().upper()
    rate = FX_TO_TWD.get(cur)
    if rate is not None:
        return float(round(amount * rate)), "TWD"
    return float(round(amount)), cur


def _money(offer: dict[str, Any]) -> tuple[float | None, str | None]:
    local_prices = offer.get("local_prices")
    if isinstance(local_prices, list) and local_prices:
        preferred = next((p for p in local_prices if isinstance(p, dict) and p.get("currency") == "TWD"), None)
        if preferred:
            offer = {**offer, "price": preferred.get("price") or preferred.get("amount"),
                     "currency": preferred.get("currency")}
    value = offer.get("price") or offer.get("fare") or offer.get("displayed_price")
    currency = offer.get("currency")
    if isinstance(value, dict):
        currency = value.get("currency") or currency
        value = value.get("amount") or value.get("value")
    try:
        amount = float(value) if value is not None else None
    except (TypeError, ValueError):
        amount = None
    return _to_twd(amount, currency)


def _clean_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    m = re.search(r"(\d{2}:\d{2})", text)
    return m.group(1) if m else text


def _flight_no(value: Any, carrier_hint: Any = None) -> str:
    if isinstance(value, dict):
        carrier = value.get("marketing_carrier_code") or value.get("airline_code") or carrier_hint or ""
        number = value.get("flight_number") or value.get("number") or ""
        value = f"{carrier}{number}"
    raw = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    hint = re.sub(r"[^A-Z0-9]", "", str(carrier_hint or "").upper())
    if hint and len(hint) == 2 and raw and raw.isdigit():
        return f"{hint}{raw}"
    return raw


def _airline_zh(raw_airline: Any, flight_number: str = "") -> str:
    code = flight_number[:2].upper() if len(flight_number) >= 2 else ""
    if code in AIRLINE_NAMES_ZH:
        return AIRLINE_NAMES_ZH[code]
    text = str(raw_airline or "").strip()
    if text.upper() in AIRLINE_NAMES_ZH:
        return AIRLINE_NAMES_ZH[text.upper()]
    lower = text.lower()
    for k, zh in (
        ("tigerair", "台灣虎航"),
        ("china airlines", "中華航空"),
        ("eva air", "長榮航空"),
        ("starlux", "星宇航空"),
        ("japan airlines", "日本航空"),
        ("all nippon", "全日空"),
        ("cathay", "國泰航空"),
        ("peach", "樂桃航空"),
        ("scoot", "酷航"),
        ("airasia", "亞洲航空"),
        ("korean air", "大韓航空"),
        ("asiana", "韓亞航空"),
        ("air busan", "釜山航空"),
        ("t'way", "德威航空"),
    ):
        if k in lower:
            return zh
    return text or code or "航班組合"


def _leg(offer: dict[str, Any], direction: str) -> dict[str, Any]:
    leg = offer.get(direction) or offer.get("legs", {}).get(direction) or {}
    segments = leg.get("segments") or leg.get("flights") or []
    first = segments[0] if segments else leg
    last = segments[-1] if segments else leg
    carrier_code = first.get("marketing_carrier_code") or first.get("airline_code") or leg.get("carrier_code")
    raw_no = first.get("flight_number") or first.get("number")
    flight_number = _flight_no(raw_no, carrier_hint=carrier_code)
    departure = first.get("departure_time_local") or first.get("departure_time") or first.get("departure")
    arrival = last.get("arrival_time_local") or last.get("arrival_time") or last.get("arrival")
    raw_airline = leg.get("carrier") or first.get("operating_carrier_name") or first.get("airline") or carrier_code
    return {
        "flight_number": flight_number,
        "departure_time": _clean_time(departure),
        "arrival_time": _clean_time(arrival),
        "stops": max(0, len(segments) - 1) if segments else int(leg.get("stops", 0) or 0),
        "airline": _airline_zh(raw_airline, flight_number),
    }


def _offers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    offers = payload.get("itineraries") or payload.get("fares") or payload.get("results") or []
    return [item for item in offers if isinstance(item, dict)] if isinstance(offers, list) else []


def _format_bags(bags: Any) -> str | None:
    if not bags:
        return None
    if isinstance(bags, str):
        clean = bags.strip()
        return None if not clean or "[object Object]" in clean else clean
    if isinstance(bags, list):
        parts = [str(x).strip() for x in bags if isinstance(x, (str, int, float)) and str(x).strip()]
        return " / ".join(parts) if parts else None
    if isinstance(bags, dict):
        parts: list[str] = []
        checked = bags.get("checked") if "checked" in bags else bags.get("checked_bags") or bags.get("hold")
        carry = bags.get("carry_on") if "carry_on" in bags else bags.get("cabin") or bags.get("hand")
        if isinstance(checked, (int, float)) and checked > 0:
            parts.append(f"托運 {int(checked)} 件")
        elif isinstance(checked, str) and checked.strip():
            parts.append(f"托運 {checked.strip()}")
        if isinstance(carry, (int, float)) and carry > 0:
            parts.append(f"手提 {int(carry)} 件")
        elif isinstance(carry, str) and carry.strip():
            parts.append(f"手提 {carry.strip()}")
        return " · ".join(parts) if parts else None
    return None


def _same_airline(out_no: str, in_no: str) -> bool:
    o = _flight_no(out_no)[:2].upper()
    i = _flight_no(in_no)[:2].upper()
    return bool(o and i and o == i)


def _itinerary(offer: dict[str, Any], origin: str, destination: str,
               outbound_date: str, return_date: str) -> dict[str, Any]:
    out_leg, in_leg = _leg(offer, "outbound"), _leg(offer, "inbound")
    amount, currency = _money(offer)
    out_airline = out_leg.get("airline") or _airline_zh(offer.get("airline") or offer.get("carrier"), out_leg.get("flight_number", ""))
    in_airline = in_leg.get("airline") or out_airline
    return {
        "origin": origin,
        "destination": destination,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "outbound": out_leg,
        "inbound": in_leg,
        "airline": out_airline if out_airline == in_airline else f"{out_airline} / {in_airline}",
        "amount": amount,
        "currency": currency or "TWD",
        "price_scope": offer.get("price_scope") or "unknown",
        "provider": offer.get("source") or "ignav",
        "ignav_id": offer.get("ignav_id"),
        "bags": _format_bags(offer.get("bags")),
        "requires_self_transfer": bool(offer.get("requires_self_transfer", False)),
    }


def itinerary_key(item: dict[str, Any]) -> str:
    out = item["outbound"]
    inbound = item["inbound"]
    return ":".join((item["outbound_date"], out["flight_number"],
                     item["return_date"], inbound["flight_number"]))


def _candidate_matches_draft(item: dict[str, Any], draft: dict[str, Any]) -> bool:
    """A tracked fare belongs to the current route, dates, and traveler party."""
    scope = item.get("_draft_scope")
    return bool(
        isinstance(scope, dict)
        and scope.get("travelers") == draft["travelers"]
        and item.get("origin") == draft["origin"]
        and item.get("destination") in draft["destinations"]
        and draft["outbound_start"] <= str(item.get("outbound_date") or "") <= draft["outbound_end"]
        and draft["return_start"] <= str(item.get("return_date") or "") <= draft["return_end"]
    )


def save_draft(payload: dict[str, Any], draft_id: str | None = None) -> dict[str, Any]:
    budget = payload.get("budget_twd")
    if budget is not None and (isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0):
        raise PlannerError("機票總預算須為大於 0 的新台幣整數。")
    normalized = {
        "origin": _airport_code(payload.get("origin", "")),
        "destinations": sorted({_airport_code(x) for x in payload.get("destinations", [])}),
        "outbound_start": payload.get("outbound_start"),
        "outbound_end": payload.get("outbound_end"),
        "return_start": payload.get("return_start"),
        "return_end": payload.get("return_end"),
        "travelers": payload.get("travelers") or {"adults": 1, "children": []},
        "budget_twd": budget,
    }
    _dates(normalized["outbound_start"], normalized["outbound_end"])
    _dates(normalized["return_start"], normalized["return_end"])
    _traveler_counts(normalized["travelers"])
    if not normalized["destinations"] or len(normalized["destinations"]) > 10:
        raise PlannerError("請選擇 1 至 10 個目的地機場。")
    draft_id = draft_id or str(uuid.uuid4())
    with _connection() as conn:
        conn.execute(
            "INSERT INTO planner_drafts(id,payload_json) VALUES(?,?) "
            "ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json,updated_at=CURRENT_TIMESTAMP",
            (draft_id, json.dumps(normalized, ensure_ascii=False)),
        )
        # Keep earlier selections for reference, but stop spending API quota on
        # flights outside the newly saved P1 conditions.
        rows = conn.execute(
            "SELECT id,payload_json FROM planner_candidates WHERE draft_id=? AND tracking_status='tracking'",
            (draft_id,),
        ).fetchall()
        for row in rows:
            if not _candidate_matches_draft(_load_json(row["payload_json"], {}), normalized):
                conn.execute(
                    "UPDATE planner_candidates SET tracking_status='paused',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (row["id"],),
                )
    return {"id": draft_id, **normalized}


def get_draft(draft_id: str) -> dict[str, Any] | None:
    with _connection() as conn:
        row = conn.execute("SELECT * FROM planner_drafts WHERE id=?", (draft_id,)).fetchone()
    return ({"id": row["id"], "updated_at": row["updated_at"], **_load_json(row["payload_json"], {})} if row else None)


def latest_draft() -> dict[str, Any] | None:
    """Return the most recently saved draft for recovery when browser storage is empty."""
    with _connection() as conn:
        row = conn.execute(
            "SELECT id,payload_json,updated_at FROM planner_drafts ORDER BY updated_at DESC,created_at DESC LIMIT 1"
        ).fetchone()
    return ({"id": row["id"], "updated_at": row["updated_at"], **_load_json(row["payload_json"], {})} if row else None)


def airport_search(query: str) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return [{"iata": a["iata"], "city": a["city"], "name": a["name"], "country": a["country"]} for a in AIRPORTS_DB[:8]]
    lower = q.lower()
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in AIRPORTS_DB:
        if (
            lower in a["iata"].lower()
            or lower in a["city"].lower()
            or lower in a["name"].lower()
            or lower in a["country"].lower()
            or lower in a["keywords"].lower()
        ):
            seen.add(a["iata"])
            result.append({"iata": a["iata"], "city": a["city"], "name": a["name"], "country": a["country"]})
    if len(q) >= 2 and len(result) < 8:
        try:
            client, ignav_error = _client()
            payload = client.search_airports(q)
            rows = payload if isinstance(payload, list) else payload.get("airports", [])
            for row in rows:
                if not isinstance(row, dict):
                    continue
                iata = str(row.get("iata") or row.get("iata_code") or row.get("code") or "").upper()
                if re.fullmatch(r"[A-Z]{3}", iata) and iata not in seen:
                    seen.add(iata)
                    result.append({
                        "iata": iata,
                        "city": row.get("city") or row.get("municipality") or "",
                        "name": row.get("name") or row.get("airport_name") or "",
                        "country": row.get("country") or "",
                    })
        except Exception:
            pass
    return result[:12]


# Known direct return flight schedules by (destination, carrier_code) to avoid extra departure_token API calls
KNOWN_RETURN_SCHEDULES: dict[tuple[str, str], list[dict[str, Any]]] = {
    ("NGO", "CI"): [
        {"flight_number": "CI151", "departure_time": "09:55", "arrival_time": "11:55", "airline": "中華航空", "delta": 0.0},
        {"flight_number": "CI155", "departure_time": "12:20", "arrival_time": "14:30", "airline": "中華航空", "delta": 0.0},
    ],
    ("NGO", "JX"): [
        {"flight_number": "JX839", "departure_time": "19:55", "arrival_time": "22:00", "airline": "星宇航空", "delta": 0.0},
    ],
    ("NGO", "CX"): [
        {"flight_number": "CX531", "departure_time": "16:40", "arrival_time": "18:50", "airline": "國泰航空", "delta": 0.0},
    ],
    ("NGO", "IT"): [
        {"flight_number": "IT207", "departure_time": "13:45", "arrival_time": "15:50", "airline": "台灣虎航", "delta": 0.0},
        {"flight_number": "IT209", "departure_time": "21:45", "arrival_time": "23:45", "airline": "台灣虎航", "delta": 0.0},
    ],
    ("NGO", "MM"): [
        {"flight_number": "MM723", "departure_time": "23:15", "arrival_time": "01:25", "airline": "樂桃航空", "delta": 0.0},
    ],
    ("HND", "IT"): [
        {"flight_number": "IT217", "departure_time": "05:25", "arrival_time": "08:00", "airline": "台灣虎航", "delta": 0.0},
    ],
    ("HND", "MM"): [
        {"flight_number": "MM859", "departure_time": "05:55", "arrival_time": "08:30", "airline": "樂桃航空", "delta": 0.0},
    ],
    ("HND", "CI"): [
        {"flight_number": "CI223", "departure_time": "07:55", "arrival_time": "10:35", "airline": "中華航空", "delta": 0.0},
        {"flight_number": "CI221", "departure_time": "14:15", "arrival_time": "16:55", "airline": "中華航空", "delta": 0.0},
    ],
    ("HND", "BR"): [
        {"flight_number": "BR189", "departure_time": "10:50", "arrival_time": "13:30", "airline": "長榮航空", "delta": 0.0},
        {"flight_number": "BR191", "departure_time": "12:15", "arrival_time": "15:05", "airline": "長榮航空", "delta": 0.0},
    ],
    ("HND", "JL"): [
        {"flight_number": "JL097", "departure_time": "08:40", "arrival_time": "11:15", "airline": "日本航空", "delta": 0.0},
        {"flight_number": "JL099", "departure_time": "18:10", "arrival_time": "20:55", "airline": "日本航空", "delta": 0.0},
    ],
    ("HND", "NH"): [
        {"flight_number": "NH851", "departure_time": "09:30", "arrival_time": "12:10", "airline": "全日空", "delta": 0.0},
        {"flight_number": "NH853", "departure_time": "13:20", "arrival_time": "15:50", "airline": "全日空", "delta": 0.0},
    ],
    ("NRT", "CI"): [
        {"flight_number": "CI101", "departure_time": "14:35", "arrival_time": "17:40", "airline": "中華航空", "delta": 0.0},
        {"flight_number": "CI105", "departure_time": "17:45", "arrival_time": "20:55", "airline": "中華航空", "delta": 0.0},
    ],
    ("NRT", "BR"): [
        {"flight_number": "BR197", "departure_time": "14:15", "arrival_time": "17:05", "airline": "長榮航空", "delta": 0.0},
        {"flight_number": "BR195", "departure_time": "20:20", "arrival_time": "23:25", "airline": "長榮航空", "delta": 0.0},
    ],
    ("NRT", "JX"): [
        {"flight_number": "JX801", "departure_time": "13:55", "arrival_time": "16:45", "airline": "星宇航空", "delta": 0.0},
        {"flight_number": "JX803", "departure_time": "16:10", "arrival_time": "19:00", "airline": "星宇航空", "delta": 0.0},
    ],
    ("NRT", "CX"): [
        {"flight_number": "CX451", "departure_time": "15:40", "arrival_time": "18:35", "airline": "國泰航空", "delta": 0.0},
    ],
    ("NRT", "JL"): [
        {"flight_number": "JL809", "departure_time": "18:05", "arrival_time": "21:15", "airline": "日本航空", "delta": 0.0},
    ],
    ("KIX", "CI"): [
        {"flight_number": "CI157", "departure_time": "13:10", "arrival_time": "15:25", "airline": "中華航空", "delta": 0.0},
        {"flight_number": "CI153", "departure_time": "14:30", "arrival_time": "16:45", "airline": "中華航空", "delta": 0.0},
        {"flight_number": "CI173", "departure_time": "19:00", "arrival_time": "21:15", "airline": "中華航空", "delta": 0.0},
    ],
    ("KIX", "BR"): [
        {"flight_number": "BR131", "departure_time": "13:10", "arrival_time": "15:05", "airline": "長榮航空", "delta": 0.0},
        {"flight_number": "BR129", "departure_time": "17:45", "arrival_time": "19:55", "airline": "長榮航空", "delta": 0.0},
    ],
    ("KIX", "JX"): [
        {"flight_number": "JX821", "departure_time": "12:20", "arrival_time": "14:20", "airline": "星宇航空", "delta": 0.0},
        {"flight_number": "JX823", "departure_time": "14:10", "arrival_time": "16:15", "airline": "星宇航空", "delta": 0.0},
    ],
    ("KIX", "CX"): [
        {"flight_number": "CX565", "departure_time": "16:15", "arrival_time": "18:30", "airline": "國泰航空", "delta": 0.0},
    ],
    ("FUK", "CI"): [
        {"flight_number": "CI111", "departure_time": "11:00", "arrival_time": "12:30", "airline": "中華航空", "delta": 0.0},
        {"flight_number": "CI117", "departure_time": "20:35", "arrival_time": "22:20", "airline": "中華航空", "delta": 0.0},
    ],
    ("FUK", "BR"): [
        {"flight_number": "BR105", "departure_time": "12:15", "arrival_time": "13:45", "airline": "長榮航空", "delta": 0.0},
        {"flight_number": "BR101", "departure_time": "19:20", "arrival_time": "20:55", "airline": "長榮航空", "delta": 0.0},
    ],
    ("FUK", "JX"): [
        {"flight_number": "JX841", "departure_time": "14:45", "arrival_time": "16:25", "airline": "星宇航空", "delta": 0.0},
    ],
    ("OKA", "CI"): [
        {"flight_number": "CI121", "departure_time": "11:55", "arrival_time": "12:35", "airline": "中華航空", "delta": 0.0},
        {"flight_number": "CI123", "departure_time": "20:35", "arrival_time": "21:15", "airline": "中華航空", "delta": 0.0},
    ],
    ("OKA", "BR"): [
        {"flight_number": "BR113", "departure_time": "10:15", "arrival_time": "10:55", "airline": "長榮航空", "delta": 0.0},
        {"flight_number": "BR185", "departure_time": "20:20", "arrival_time": "21:05", "airline": "長榮航空", "delta": 0.0},
    ],
    ("OKA", "JX"): [
        {"flight_number": "JX871", "departure_time": "15:35", "arrival_time": "16:15", "airline": "星宇航空", "delta": 0.0},
    ],
    ("KMJ", "CI"): [
        {"flight_number": "CI195", "departure_time": "18:30", "arrival_time": "20:00", "airline": "中華航空", "delta": 0.0},
        {"flight_number": "CI199", "departure_time": "11:50", "arrival_time": "13:25", "airline": "中華航空", "delta": 0.0},
    ],
    ("KMJ", "JX"): [
        {"flight_number": "JX847", "departure_time": "12:00", "arrival_time": "13:40", "airline": "星宇航空", "delta": 0.0},
    ],
    ("CTS", "CI"): [
        {"flight_number": "CI131", "departure_time": "14:40", "arrival_time": "18:15", "airline": "中華航空", "delta": 0.0},
    ],
    ("CTS", "BR"): [
        {"flight_number": "BR115", "departure_time": "16:00", "arrival_time": "19:30", "airline": "長榮航空", "delta": 0.0},
        {"flight_number": "BR165", "departure_time": "12:10", "arrival_time": "15:40", "airline": "長榮航空", "delta": 0.0},
    ],
    ("CTS", "JX"): [
        {"flight_number": "JX851", "departure_time": "15:00", "arrival_time": "18:30", "airline": "星宇航空", "delta": 0.0},
    ],
}


def _cache_key(origin: str, destination: str, outbound: str, inbound: str, adults: int, children: int) -> str:
    return f"serp:{origin}:{destination}:{outbound}:{inbound}:A{adults}C{children}"


def _serpapi_search_combinations(
    origin: str,
    combinations: list[tuple[str, str, str]],
    adults: int,
    children: int,
    hist_items: list[dict[str, Any]] | None = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    api_key = _get_serpapi_key()
    if not api_key or not combinations:
        return []

    pax_total = adults + children
    scope_label = f"party_of_{pax_total} (SerpApi)"

    # Step 0: Check 24-hour SQLite search cache first (0 API quota for already-searched combinations)
    cached_results: list[dict[str, Any]] = []
    uncached_combos: list[tuple[str, str, str]] = []
    if use_cache:
        with _connection() as conn:
            for combo in combinations:
                outbound, inbound, destination = combo
                ck = _cache_key(origin, destination, outbound, inbound, adults, children)
                row = conn.execute(
                    "SELECT payload_json,cached_at FROM planner_search_cache "
                    "WHERE cache_key=? AND cached_at >= datetime('now', ?)",
                    (ck, f"-{price_freshness_hours()} hours"),
                ).fetchone()
                if row:
                    items = _load_json(row["payload_json"], [])
                    if isinstance(items, list):
                        cached_results.extend({**item, "observed_at": item.get("observed_at") or f"{row['cached_at']}Z", "data_age_source": "cache"} for item in items if isinstance(item, dict))
                        continue
                uncached_combos.append(combo)
    else:
        uncached_combos = list(combinations)

    if not uncached_combos:
        return cached_results

    # Seed fallback same-airline return templates from historical snapshots + KNOWN_RETURN_SCHEDULES
    hist_templates: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for h in hist_items or []:
        dest = h.get("destination") or ""
        out_no = (h.get("outbound") or {}).get("flight_number") or ""
        in_leg = h.get("inbound") or {}
        in_no = in_leg.get("flight_number") or ""
        if dest and out_no and in_no and not in_leg.get("stops") and _same_airline(out_no, in_no):
            hist_templates.setdefault((dest, out_no), {})[in_no] = {
                "flight_number": in_no,
                "departure_time": _clean_time(in_leg.get("departure_time")),
                "arrival_time": _clean_time(in_leg.get("arrival_time")),
                "stops": 0,
                "airline": _airline_zh(in_leg.get("airline"), in_no),
                "delta": 0.0,
            }

    def _known_templates_for(destination: str, out_no: str) -> dict[str, dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        carrier = _flight_no(out_no)[:2].upper()
        for tpl in KNOWN_RETURN_SCHEDULES.get((destination, carrier), []):
            merged[tpl["flight_number"]] = {**tpl, "stops": 0}
        for in_no, tpl in hist_templates.get((destination, out_no), {}).items():
            merged[in_no] = tpl
        return merged

    def _base_params(outbound: str, inbound: str, destination: str) -> dict[str, Any]:
        return {
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": outbound,
            "return_date": inbound,
            "type": 1,
            "travel_class": 1,
            "adults": adults,
            "children": children,
            "stops": 1,
            "currency": "TWD",
            "gl": "tw",
            "hl": "zh-TW",
            "api_key": api_key,
        }

    # Step 1: Deduplicate market_scan by (destination, outbound) so multiple return dates share 1 scan
    rep_combos: dict[tuple[str, str], tuple[str, str, str]] = {}
    for outbound, inbound, destination in uncached_combos:
        rep_combos.setdefault((destination, outbound), (outbound, inbound, destination))

    rep_scans: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def _fetch_market(combo: tuple[str, str, str]) -> tuple[tuple[str, str, str], dict[str, Any] | None]:
        outbound, inbound, destination = combo
        try:
            return combo, _serpapi_request(_base_params(outbound, inbound, destination))
        except Exception:
            return combo, None

    unique_reps = list(rep_combos.values())
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(unique_reps))) as pool:
        for (outbound, inbound, destination), data in pool.map(_fetch_market, unique_reps):
            if not isinstance(data, dict):
                continue
            outbound_candidates: list[dict[str, Any]] = []
            seen_out: set[str] = set()
            for raw_item in [*(data.get("best_flights") or []), *(data.get("other_flights") or [])]:
                flights = raw_item.get("flights") or []
                if len(flights) != 1:
                    continue
                seg = flights[0]
                out_no = _flight_no(seg.get("flight_number"))
                if not out_no or out_no in seen_out:
                    continue
                seen_out.add(out_no)
                base_price, _ = _to_twd(raw_item.get("price"), "TWD")
                out_airline = _airline_zh(seg.get("airline"), out_no)
                outbound_candidates.append({
                    "out_no": out_no,
                    "outbound": {
                        "flight_number": out_no,
                        "departure_time": _clean_time((seg.get("departure_airport") or {}).get("time")),
                        "arrival_time": _clean_time((seg.get("arrival_airport") or {}).get("time")),
                        "stops": 0,
                        "airline": out_airline,
                    },
                    "base_price": base_price,
                    "departure_token": raw_item.get("departure_token"),
                })
            rep_scans[(destination, outbound)] = outbound_candidates

    market_scans: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for combo in uncached_combos:
        outbound, inbound, destination = combo
        if (destination, outbound) in rep_scans:
            market_scans[combo] = rep_scans[(destination, outbound)]

    if not market_scans:
        return cached_results

    # Step 2: Only expand departure_token when a flight has NO known return template (saves ~80% token calls)
    token_jobs: list[tuple[str, str, str, str, float | None, str]] = []
    seen_dest_out: set[tuple[str, str]] = set()
    dest_counts: dict[str, int] = {}

    all_candidates: list[tuple[int, float, str, str, str, dict[str, Any]]] = []
    for (outbound, inbound, destination), cand_list in market_scans.items():
        for cand in cand_list:
            token = cand.get("departure_token")
            out_no = cand["out_no"]
            if not token or _known_templates_for(destination, out_no):
                continue
            is_fsc = 0 if out_no[:2].upper() in _FSC_PREFIXES else 1
            price_sort = cand["base_price"] if cand["base_price"] is not None else 999999.0
            all_candidates.append((is_fsc, price_sort, outbound, inbound, destination, cand))

    all_candidates.sort(key=lambda x: (x[0], x[1]))
    for _, _, outbound, inbound, destination, cand in all_candidates:
        out_no = cand["out_no"]
        if (destination, out_no) in seen_dest_out:
            continue
        if dest_counts.get(destination, 0) >= 2:
            continue
        seen_dest_out.add((destination, out_no))
        dest_counts[destination] = dest_counts.get(destination, 0) + 1
        token_jobs.append((outbound, inbound, destination, out_no, cand["base_price"], cand["departure_token"]))

    exact_returns: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    live_templates: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    def _fetch_token(job: tuple[str, str, str, str, float | None, str]):
        outbound, inbound, destination, out_no, base_price, token = job
        params = _base_params(outbound, inbound, destination)
        params["departure_token"] = token
        try:
            return job, _serpapi_request(params)
        except Exception:
            return job, None

    if token_jobs:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(token_jobs))) as pool:
            for (outbound, inbound, destination, out_no, base_price, _), ret_data in pool.map(_fetch_token, token_jobs):
                if not isinstance(ret_data, dict):
                    continue
                ret_list: list[dict[str, Any]] = []
                seen_in: set[str] = set()
                for ret_item in [*(ret_data.get("best_flights") or []), *(ret_data.get("other_flights") or [])]:
                    r_flights = ret_item.get("flights") or []
                    if len(r_flights) != 1:
                        continue
                    r_seg = r_flights[0]
                    in_no = _flight_no(r_seg.get("flight_number"))
                    if not in_no or in_no in seen_in or not _same_airline(out_no, in_no):
                        continue
                    seen_in.add(in_no)
                    ret_price, _ = _to_twd(ret_item.get("price") or base_price, "TWD")
                    in_airline = _airline_zh(r_seg.get("airline"), in_no)
                    delta = max(0.0, (ret_price or 0.0) - (base_price or 0.0)) if (ret_price and base_price) else 0.0
                    in_entry = {
                        "flight_number": in_no,
                        "departure_time": _clean_time((r_seg.get("departure_airport") or {}).get("time")),
                        "arrival_time": _clean_time((r_seg.get("arrival_airport") or {}).get("time")),
                        "stops": 0,
                        "airline": in_airline,
                        "amount": ret_price,
                        "delta": delta,
                    }
                    ret_list.append(in_entry)
                    live_templates.setdefault((destination, out_no), {})[in_no] = in_entry
                if ret_list:
                    exact_returns[(outbound, inbound, destination, out_no)] = ret_list

    # Step 3: Assemble full nonstop same-airline roundtrip itineraries and persist to 24h SQLite cache
    fresh_by_combo: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for (outbound, inbound, destination), cand_list in market_scans.items():
        combo_items: list[dict[str, Any]] = []
        for cand in cand_list:
            out_no = cand["out_no"]
            out_leg = cand["outbound"]
            base_price = cand["base_price"]
            ret_entries = exact_returns.get((outbound, inbound, destination, out_no))
            if not ret_entries:
                tpl_map = live_templates.get((destination, out_no)) or _known_templates_for(destination, out_no)
                ret_entries = [
                    {
                        **tpl,
                        "amount": round(base_price + float(tpl.get("delta") or 0.0)) if base_price is not None else tpl.get("amount"),
                    }
                    for tpl in tpl_map.values()
                ]
            for ret in ret_entries:
                if not _same_airline(out_no, ret["flight_number"]):
                    continue
                in_leg = {
                    "flight_number": ret["flight_number"],
                    "departure_time": ret["departure_time"],
                    "arrival_time": ret["arrival_time"],
                    "stops": 0,
                    "airline": ret["airline"],
                }
                out_airline = out_leg["airline"]
                combo_items.append({
                    "origin": origin,
                    "destination": destination,
                    "outbound_date": outbound,
                    "return_date": inbound,
                    "outbound": out_leg,
                    "inbound": in_leg,
                    "airline": out_airline,
                    "amount": ret.get("amount") if ret.get("amount") is not None else base_price,
                    "currency": "TWD",
                    "price_scope": scope_label,
                    "provider": "serpapi",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "data_age_source": "live",
                    "ignav_id": None,
                    "bags": None,
                    "requires_self_transfer": False,
                })
        fresh_by_combo[(outbound, inbound, destination)] = combo_items

    if use_cache and fresh_by_combo:
        with _connection() as conn:
            for (outbound, inbound, destination), items in fresh_by_combo.items():
                ck = _cache_key(origin, destination, outbound, inbound, adults, children)
                conn.execute(
                    "INSERT INTO planner_search_cache(cache_key,payload_json,cached_at) VALUES(?,?,CURRENT_TIMESTAMP) "
                    "ON CONFLICT(cache_key) DO UPDATE SET payload_json=excluded.payload_json,cached_at=CURRENT_TIMESTAMP",
                    (ck, json.dumps(items, ensure_ascii=False)),
                )

    all_fresh = [item for items in fresh_by_combo.values() for item in items]
    return [*cached_results, *all_fresh]


@operation("P1")
def search_draft(draft_id: str) -> list[dict[str, Any]]:
    draft = get_draft(draft_id)
    if not draft:
        raise PlannerError("找不到旅程草案，請先儲存搜尋條件。")
    adults, children, has_infant = _traveler_counts(draft["travelers"])
    if has_infant:
        raise PlannerError("目前旅客設定含未滿 2 歲旅客；請先補上嬰兒抱坐／佔位選擇後再查價。")
    out_dates = _dates(draft["outbound_start"], draft["outbound_end"])
    return_dates = _dates(draft["return_start"], draft["return_end"])
    combinations = [(d, r, dest) for dest in draft["destinations"] for d in out_dates for r in return_dates if r > d]
    if len(combinations) > 36:
        raise PlannerError("目前日期與目的地組合超過 36 組。請縮小搜尋區間後再查詢。")

    found: dict[str, dict[str, Any]] = {}
    # 1. Include matching roundtrip snapshots from local SQLite & SerpApi monitor history
    out_set, ret_set = set(out_dates), set(return_dates)
    all_hist = historical_itineraries(draft_id)
    for hist_item in all_hist:
        if hist_item["outbound_date"] in out_set and hist_item["return_date"] in ret_set:
            if not hist_item["outbound"]["stops"] and not hist_item["inbound"]["stops"]:
                if _same_airline(hist_item["outbound"]["flight_number"], hist_item["inbound"]["flight_number"]):
                    found[itinerary_key(hist_item)] = hist_item

    # 2. Query live SerpApi Google Flights (with 24h SQLite cache + known-schedule pairing)
    for serp_item in _serpapi_search_combinations(draft["origin"], combinations, adults, children, all_hist):
        key = itinerary_key(serp_item)
        current = found.get(key)
        if not current or str(current.get("provider", "")).startswith("history:") or current.get("amount") is None:
            found[key] = serp_item

    # 3. Query live Ignav provider (LCC & supplementary fares + ignav_id for P3 booking links)
    try:
        client, ignav_error = _client()
    except PlannerError:
        if found:
            return sorted(found.values(), key=lambda x: (x["outbound_date"], x["destination"], x["amount"] is None, x["amount"] or 0))
        raise

    for outbound, inbound, destination in combinations:
        try:
            payload = client.search_round_trip(
                origin=draft["origin"], destination=destination,
                departure_date=outbound, return_date=inbound,
                adults=adults, children=children, currency="TWD",
            )
        except ignav_error as exc:
            if found:
                break
            raise PlannerError("航班供應商查詢失敗；沒有新增未確認的航班資料。") from exc
        for raw in _offers(payload):
            item = _itinerary(raw, draft["origin"], destination, outbound, inbound)
            item["observed_at"] = datetime.now(timezone.utc).isoformat()
            item["data_age_source"] = "live"
            out_no = item["outbound"]["flight_number"]
            in_no = item["inbound"]["flight_number"]
            if not out_no or not in_no or not _same_airline(out_no, in_no):
                continue
            if item["outbound"]["stops"] or item["inbound"]["stops"]:
                continue
            key = itinerary_key(item)
            current = found.get(key)
            if not current:
                found[key] = item
            elif current.get("provider") == "serpapi":
                # Keep SerpApi's TWD family/party fare, attach ignav_id from Ignav for P3 booking
                if item.get("ignav_id") and not current.get("ignav_id"):
                    current["ignav_id"] = item["ignav_id"]
                    current["provider"] = "serpapi+ignav"
                if item.get("bags") and not current.get("bags"):
                    current["bags"] = item["bags"]
                if current.get("amount") is None and item.get("amount") is not None:
                    current["amount"] = item["amount"]
            elif item["amount"] is not None and current.get("amount") is None:
                found[key] = item
    return sorted(found.values(), key=lambda x: (x["outbound_date"], x["destination"], x["amount"] is None, x["amount"] or 0))


def add_candidate(draft_id: str, itinerary: dict[str, Any]) -> dict[str, Any]:
    draft = get_draft(draft_id)
    if not draft:
        raise PlannerError("找不到旅程草案。")
    if not (
        itinerary.get("origin") == draft["origin"]
        and itinerary.get("destination") in draft["destinations"]
        and draft["outbound_start"] <= str(itinerary.get("outbound_date") or "") <= draft["outbound_end"]
        and draft["return_start"] <= str(itinerary.get("return_date") or "") <= draft["return_end"]
    ):
        raise PlannerError("航班日期或地點不在目前 P1 草案範圍內，請重新搜尋。")
    key = itinerary_key(itinerary)
    candidate_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{draft_id}:{key}"))
    amt, cur = _to_twd(itinerary.get("amount"), itinerary.get("currency"))
    itinerary = {**itinerary, "_draft_scope": {"travelers": draft["travelers"]}}
    if amt is not None:
        itinerary = {**itinerary, "amount": amt, "currency": cur or "TWD"}
    with _connection() as conn:
        existing = conn.execute(
            "SELECT payload_json FROM planner_candidates WHERE draft_id=? AND itinerary_key=?",
            (draft_id, key),
        ).fetchone()
        if existing and not _candidate_matches_draft(_load_json(existing["payload_json"], {}), draft):
            raise PlannerError("這組航班已有不同旅客條件的舊候選；請先到 P2 的舊候選清單移除，再重新加入。")
        conn.execute(
            "INSERT INTO planner_candidates(id,draft_id,itinerary_key,payload_json,target_price) VALUES(?,?,?,?,?) "
            "ON CONFLICT(draft_id,itinerary_key) DO NOTHING",
            (candidate_id, draft_id, key, json.dumps(itinerary, ensure_ascii=False), draft.get("budget_twd")),
        )
        row = conn.execute("SELECT * FROM planner_candidates WHERE draft_id=? AND itinerary_key=?", (draft_id, key)).fetchone()
        observed_at = itinerary.get("observed_at")
        if itinerary.get("amount") and observed_at:
            conn.execute(
                "INSERT OR IGNORE INTO planner_price_observations "
                "(candidate_id,source,amount,currency,price_scope,observed_at) VALUES(?,?,?,?,?,?)",
                (row["id"], itinerary.get("provider", "ignav"), itinerary["amount"],
                 itinerary.get("currency") or "TWD", itinerary.get("price_scope") or "unknown", observed_at),
            )
    return _candidate_from_row(row)


def _serpapi_csv_observations(item: dict[str, Any]) -> list[dict[str, Any]]:
    if not _NAGOYA_ITIN_CSV.exists():
        return []
    out_no = _flight_no((item.get("outbound") or {}).get("flight_number"))
    in_no = _flight_no((item.get("inbound") or {}).get("flight_number"))
    out_date = item.get("outbound_date")
    in_date = item.get("return_date")
    if not (out_no and in_no and out_date and in_date):
        return []
    result: list[dict[str, Any]] = []
    try:
        with _NAGOYA_ITIN_CSV.open(newline="", encoding="utf-8") as stream:
            for r in csv.DictReader(stream):
                csv_out_no = _flight_no(r.get("outbound_flight"), r.get("airline_iata", ""))
                csv_in_no = _flight_no(r.get("inbound_flight"), r.get("inbound_airline_iata", ""))
                csv_out_date = str(r.get("outbound_departure") or "")[:10]
                csv_in_date = str(r.get("inbound_departure") or "")[:10]
                if (csv_out_no, csv_in_no, csv_out_date, csv_in_date) != (out_no, in_no, out_date, in_date):
                    continue
                price_raw = r.get("family_total_twd") or r.get("displayed_price_twd")
                if not price_raw:
                    continue
                try:
                    amt = float(price_raw)
                except ValueError:
                    continue
                result.append({
                    "source": "history:SerpApi",
                    "amount": amt,
                    "currency": "TWD",
                    "price_scope": r.get("price_scope") or "family_2A2C",
                    "observed_at": r.get("checked_at"),
                })
    except Exception:
        return []
    return result


def _legacy_observations(conn: Any, item: dict[str, Any]) -> list[dict[str, Any]]:
    out_no = (item.get("outbound") or {}).get("flight_number")
    in_no = (item.get("inbound") or {}).get("flight_number")
    out_date = item.get("outbound_date")
    in_date = item.get("return_date")
    if not (out_no and in_no and out_date and in_date):
        return []
    rows = conn.execute(
        """
        SELECT rt.source, rt.price_twd, rt.passenger_count,
               COALESCE(rt.captured_at, rt.last_checked_at) AS observed_at
        FROM roundtrip_price_snapshots rt
        JOIN flight_instances ob ON ob.id = rt.outbound_flight_instance_id
        JOIN flight_instances ib ON ib.id = rt.inbound_flight_instance_id
        WHERE ob.flight_date = ? AND ob.flight_number = ?
          AND ib.flight_date = ? AND ib.flight_number = ?
        ORDER BY observed_at ASC
        """,
        (out_date, out_no, in_date, in_no),
    ).fetchall()
    result = []
    for r in rows:
        pax = int(r["passenger_count"] or 1)
        result.append({
            "source": f"history:{r['source']}",
            "amount": float(r["price_twd"]),
            "currency": "TWD",
            "price_scope": "per_person" if pax == 1 else f"party_of_{pax}",
            "observed_at": r["observed_at"],
        })
    result.extend(_serpapi_csv_observations(item))
    return result


def _normalize_stored_itinerary(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item.get("outbound") or {})
    inb = dict(item.get("inbound") or {})
    out["departure_time"] = _clean_time(out.get("departure_time"))
    out["arrival_time"] = _clean_time(out.get("arrival_time"))
    inb["departure_time"] = _clean_time(inb.get("departure_time"))
    inb["arrival_time"] = _clean_time(inb.get("arrival_time"))
    amt, cur = _to_twd(item.get("amount"), item.get("currency"))
    return {
        **item,
        "outbound": out,
        "inbound": inb,
        "airline": _airline_zh(item.get("airline"), out.get("flight_number", "")),
        "amount": amt if amt is not None else item.get("amount"),
        "currency": cur or item.get("currency") or "TWD",
        "bags": _format_bags(item.get("bags")),
    }


def _candidate_from_row(row: Any) -> dict[str, Any]:
    item = _normalize_stored_itinerary(_load_json(row["payload_json"], {}))
    with _connection() as conn:
        # Older builds stamped cached P1 prices with candidate creation time.
        # Restore their actual provider timestamp so they cannot pass freshness checks.
        if item.get("data_age_source") == "cache" and item.get("observed_at") and item.get("amount") is not None:
            if str(item["observed_at"]) != str(row["created_at"]):
                conn.execute(
                    "DELETE FROM planner_price_observations AS stale WHERE stale.candidate_id=? "
                    "AND stale.source=? AND stale.amount=? AND stale.currency=? AND stale.observed_at=? "
                    "AND EXISTS (SELECT 1 FROM planner_price_observations AS actual "
                    "WHERE actual.candidate_id=stale.candidate_id AND actual.source=stale.source "
                    "AND actual.amount=stale.amount AND actual.currency=stale.currency AND actual.observed_at=?)",
                    (row["id"], item.get("provider", "ignav"), item["amount"], item.get("currency") or "TWD",
                     row["created_at"], item["observed_at"]),
                )
            conn.execute(
                "UPDATE planner_price_observations SET observed_at=? "
                "WHERE candidate_id=? AND source=? AND amount=? AND currency=? AND observed_at=?",
                (item["observed_at"], row["id"], item.get("provider", "ignav"), item["amount"],
                 item.get("currency") or "TWD", row["created_at"]),
            )
        raw_live = [dict(x) for x in conn.execute(
            "SELECT source,amount,currency,price_scope,observed_at FROM planner_price_observations "
            "WHERE candidate_id=? ORDER BY observed_at", (row["id"],),
        ).fetchall()]
        legacy_obs = _legacy_observations(conn, item)
    live_obs = []
    for obs in raw_live:
        amt, cur = _to_twd(obs.get("amount"), obs.get("currency"))
        live_obs.append({**obs, "amount": amt if amt is not None else obs.get("amount"), "currency": cur or "TWD"})
    merged = sorted(
        [*legacy_obs, *live_obs],
        key=lambda x: str(x.get("observed_at") or ""),
    )
    return {"id": row["id"], "tracking_status": row["tracking_status"],
            "last_refresh_attempt_at": row["last_refresh_attempt_at"],
            "tracking_interval_hours": tracking_interval_hours(),
            "target_price": row["target_price"], "observations": merged,
            "itinerary": item,
            "channel_comparison": _channel_comparison(item)}


def _serpapi_monitor_itineraries(draft: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not _NAGOYA_LATEST_JSON.exists():
        return []
    try:
        data = json.loads(_NAGOYA_LATEST_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    route = data.get("route") or {}
    origin = str(route.get("origin") or "TPE").upper()
    dest = str(route.get("destination") or "NGO").upper()
    if draft:
        if origin != draft["origin"]:
            return []
        if draft["destinations"] and dest not in draft["destinations"]:
            return []
    results: list[dict[str, Any]] = []
    for it in data.get("itineraries") or []:
        out_no = _flight_no(it.get("outbound_flight"), it.get("airline_iata", ""))
        in_no = _flight_no(it.get("inbound_flight"), it.get("inbound_airline_iata", ""))
        out_dep_raw = str(it.get("outbound_departure") or "")
        in_dep_raw = str(it.get("inbound_departure") or "")
        out_date = out_dep_raw[:10] or str(route.get("outbound_date") or "")
        in_date = in_dep_raw[:10] or str(route.get("inbound_date") or "")
        if not (out_no and in_no and out_date and in_date):
            continue
        amt = it.get("family_total_twd") or it.get("displayed_price_twd")
        if amt is None:
            continue
        out_airline = _airline_zh(it.get("airline") or it.get("airline_iata"), out_no)
        in_airline = _airline_zh(it.get("inbound_airline_iata"), in_no)
        ver = it.get("price_verification") or {}
        bags_list = ver.get("baggage_prices") if isinstance(ver, dict) else None
        scope = "family_total (2大2小驗證)" if it.get("price_scope") == "family_total" else (it.get("price_scope") or "unknown")
        results.append({
            "origin": origin,
            "destination": dest,
            "outbound_date": out_date,
            "return_date": in_date,
            "outbound": {
                "flight_number": out_no,
                "departure_time": _clean_time(out_dep_raw),
                "arrival_time": _clean_time(it.get("outbound_arrival")),
                "stops": 0,
                "airline": out_airline,
            },
            "inbound": {
                "flight_number": in_no,
                "departure_time": _clean_time(in_dep_raw),
                "arrival_time": _clean_time(it.get("inbound_arrival")),
                "stops": 0,
                "airline": in_airline,
            },
            "airline": out_airline if out_airline == in_airline else f"{out_airline} / {in_airline}",
            "amount": float(amt),
            "currency": "TWD",
            "price_scope": scope,
            "provider": "history:SerpApi",
            "observed_at": it.get("checked_at") or data.get("checked_at"),
            "data_age_source": "history",
            "ignav_id": None,
            "bags": " / ".join(bags_list) if isinstance(bags_list, list) and bags_list else None,
            "requires_self_transfer": False,
            "historical_low_twd": it.get("historical_low_twd"),
        })
    return results


def historical_itineraries(draft_id: str | None = None) -> list[dict[str, Any]]:
    draft = get_draft(draft_id) if draft_id else None
    found: dict[str, dict[str, Any]] = {}
    # 1. Include SerpApi Google Flights monitored itineraries (e.g. CI154+CI155, CI154+CI151, JX838+JX839, CX530+CX531)
    for item in _serpapi_monitor_itineraries(draft):
        found[itinerary_key(item)] = item

    # 2. Include SQLite roundtrip_price_snapshots
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT rt.source, rt.price_twd, rt.passenger_count,
                   COALESCE(rt.last_checked_at, rt.captured_at) AS observed_at,
                   ob.origin_airport, ob.dest_airport,
                   ob.flight_date AS outbound_date, ob.airline_code AS outbound_airline,
                   ob.flight_number AS outbound_flight_number,
                   ob.departure_time AS outbound_departure_time,
                   ob.arrival_time AS outbound_arrival_time,
                   ob.stops AS outbound_stops,
                   ib.flight_date AS return_date, ib.airline_code AS inbound_airline,
                   ib.flight_number AS inbound_flight_number,
                   ib.departure_time AS inbound_departure_time,
                   ib.arrival_time AS inbound_arrival_time,
                   ib.stops AS inbound_stops
            FROM roundtrip_price_snapshots rt
            JOIN flight_instances ob ON ob.id = rt.outbound_flight_instance_id
            JOIN flight_instances ib ON ib.id = rt.inbound_flight_instance_id
            ORDER BY observed_at DESC, rt.price_twd ASC
            """
        ).fetchall()
    for r in rows:
        if draft:
            if r["origin_airport"] != draft["origin"]:
                continue
            if draft["destinations"] and r["dest_airport"] not in draft["destinations"]:
                continue
        pax = int(r["passenger_count"] or 1)
        out_no = _flight_no(r["outbound_flight_number"], r["outbound_airline"])
        in_no = _flight_no(r["inbound_flight_number"], r["inbound_airline"])
        airline_name = _airline_zh(r["outbound_airline"], out_no)
        item = {
            "origin": r["origin_airport"],
            "destination": r["dest_airport"],
            "outbound_date": r["outbound_date"],
            "return_date": r["return_date"],
            "outbound": {
                "flight_number": out_no,
                "departure_time": _clean_time(r["outbound_departure_time"]),
                "arrival_time": _clean_time(r["outbound_arrival_time"]),
                "stops": int(r["outbound_stops"] or 0),
                "airline": airline_name,
            },
            "inbound": {
                "flight_number": in_no,
                "departure_time": _clean_time(r["inbound_departure_time"]),
                "arrival_time": _clean_time(r["inbound_arrival_time"]),
                "stops": int(r["inbound_stops"] or 0),
                "airline": _airline_zh(r["inbound_airline"], in_no),
            },
            "airline": airline_name,
            "amount": float(r["price_twd"]),
            "currency": "TWD",
            "price_scope": "per_person" if pax == 1 else f"party_of_{pax}",
            "provider": f"history:{r['source']}",
            "observed_at": r["observed_at"],
            "data_age_source": "history",
            "ignav_id": None,
            "bags": None,
            "requires_self_transfer": False,
        }
        key = itinerary_key(item)
        if key not in found:
            found[key] = item
    return sorted(found.values(), key=lambda x: (x["outbound_date"], x["destination"], x["amount"] is None, x["amount"] or 0))


def list_candidates(draft_id: str) -> list[dict[str, Any]]:
    draft = get_draft(draft_id)
    with _connection() as conn:
        rows = conn.execute(
            "SELECT * FROM planner_candidates WHERE draft_id=? ORDER BY created_at", (draft_id,),
        ).fetchall()
    candidates = [_candidate_from_row(row) for row in rows]
    for candidate in candidates:
        candidate["matches_current_draft"] = bool(
            draft and _candidate_matches_draft(candidate["itinerary"], draft)
        )
    return candidates


def set_candidate(candidate_id: str, status: str | None = None,
                  target_price: float | None = None,
                  update_target: bool = False) -> dict[str, Any] | None:
    with _connection() as conn:
        row = conn.execute("SELECT * FROM planner_candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            return None
        if status is not None:
            if status not in ("tracking", "paused"):
                raise PlannerError("追蹤狀態不正確。")
            conn.execute("UPDATE planner_candidates SET tracking_status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (status, candidate_id))
        if target_price is not None:
            if target_price < 0:
                raise PlannerError("目標價不可小於 0。")
            conn.execute("UPDATE planner_candidates SET target_price=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (target_price, candidate_id))
        elif update_target:
            conn.execute("UPDATE planner_candidates SET target_price=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (candidate_id,))
        row = conn.execute("SELECT * FROM planner_candidates WHERE id=?", (candidate_id,)).fetchone()
    return _candidate_from_row(row)


def remove_candidate(candidate_id: str) -> bool:
    with _connection() as conn:
        conn.execute("DELETE FROM planner_decisions WHERE candidate_id=?", (candidate_id,))
        return conn.execute("DELETE FROM planner_candidates WHERE id=?", (candidate_id,)).rowcount > 0


@operation("P2")
def refresh_candidate(candidate_id: str) -> dict[str, Any]:
    with _connection() as conn:
        row = conn.execute("SELECT * FROM planner_candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        raise PlannerError("找不到航班候選。")
    with _connection() as conn:
        conn.execute(
            "UPDATE planner_candidates SET last_refresh_attempt_at=CURRENT_TIMESTAMP WHERE id=?",
            (candidate_id,),
        )
    candidate = _candidate_from_row(row)
    item = candidate["itinerary"]
    draft = get_draft(row["draft_id"])
    adults, children, infant = _traveler_counts(draft["travelers"])
    if infant:
        raise PlannerError("旅客含未滿 2 歲嬰兒，尚未設定抱坐／佔位，無法查詢可比較票價。")
    expected = itinerary_key(item)
    matches: list[dict[str, Any]] = []

    # 1. Try SerpApi Google Flights first (covers traditional flag carriers + LCCs in TWD)
    combo = [(item["outbound_date"], item["return_date"], item["destination"])]
    for serp_res in _serpapi_search_combinations(item["origin"], combo, adults, children, [item], use_cache=False):
        if itinerary_key(serp_res) == expected:
            matches.append(serp_res)

    # 2. Also query Ignav
    try:
        client, ignav_error = _client()
        payload = client.search_round_trip(
            origin=item["origin"], destination=item["destination"],
            departure_date=item["outbound_date"], return_date=item["return_date"],
            adults=adults, children=children, currency="TWD",
        )
        for raw in _offers(payload):
            result = _itinerary(raw, item["origin"], item["destination"], item["outbound_date"], item["return_date"])
            if itinerary_key(result) == expected:
                matches.append(result)
    except Exception as exc:
        if not matches:
            with _connection() as conn:
                conn.execute("UPDATE planner_candidates SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (candidate_id,))
            raise PlannerError("航班價格更新失敗，保留既有價格紀錄。") from exc

    observed = [m for m in matches if m.get("amount")]
    with _connection() as conn:
        for fare in observed:
            conn.execute(
                "INSERT OR IGNORE INTO planner_price_observations "
                "(candidate_id,source,amount,currency,price_scope,observed_at) VALUES(?,?,?,?,?,?)",
                (candidate_id, fare["provider"], fare["amount"], fare["currency"] or "TWD",
                 fare["price_scope"], fare.get("observed_at") or datetime.now(timezone.utc).isoformat()),
            )
        conn.execute("UPDATE planner_candidates SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (candidate_id,))
    return {"candidate": next((c for c in list_candidates(row["draft_id"]) if c["id"] == candidate_id), None),
            "new_observations": len(observed), "checked_at": datetime.now(timezone.utc).isoformat()}


def refresh_stale_candidates(draft_id: str) -> dict[str, Any]:
    """Refresh tracked P2 candidates whose latest non-history observation expired."""
    if not get_draft(draft_id):
        raise PlannerError("找不到旅程草案。")
    checked = refreshed = observations = failed = 0
    errors: list[dict[str, str]] = []
    for candidate in list_candidates(draft_id):
        if not candidate.get("matches_current_draft") or candidate.get("tracking_status") != "tracking":
            continue
        checked += 1
        live = [o for o in candidate.get("observations", [])
                if not str(o.get("source") or "").lower().startswith("history:")]
        latest = live[-1] if live else None
        if latest and _is_quote_fresh(latest.get("observed_at")):
            continue
        try:
            result = refresh_candidate(candidate["id"])
            refreshed += 1
            observations += int(result.get("new_observations") or 0)
        except Exception as exc:
            failed += 1
            errors.append({"candidate_id": candidate["id"], "error": str(exc)})
    return {"checked": checked, "refreshed": refreshed, "new_observations": observations,
            "failed": failed, "errors": errors}


def tracking_interval_hours() -> int:
    try:
        configured = int((load_settings().get("planner") or {}).get("tracking_interval_hours", os.environ.get("PLANNER_REFRESH_INTERVAL_HOURS", "6")))
    except (ValueError, TypeError):
        configured = 6
    return max(1, min(168, configured))


def _tracking_loop() -> None:
    while not _scheduler_stop.wait(900):
        interval = tracking_interval_hours()
        with _connection() as conn:
            rows = conn.execute(
                "SELECT c.* FROM planner_candidates c WHERE c.tracking_status='tracking'",
            ).fetchall()
        for row in rows:
            if _scheduler_stop.is_set():
                break
            try:
                last_attempt = row["last_refresh_attempt_at"]
                if last_attempt and _is_quote_fresh(last_attempt, max_age_hours=interval):
                    continue
                # Scheduled observations are collected even while the last price is fresh.
                refresh_candidate(row["id"])
            except Exception:
                # Provider failures leave the last successful observation intact.
                with _connection() as conn:
                    conn.execute("UPDATE planner_candidates SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                 (row["id"],))
                continue


def start_tracking_scheduler() -> None:
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_stop.clear()
        threading.Thread(target=_tracking_loop, name="planner-price-tracker", daemon=True).start()
        _scheduler_started = True


AIRLINE_OFFICIAL_URLS: dict[str, str] = {
    "CI": "https://www.china-airlines.com/tw/zh",
    "BR": "https://www.evaair.com/zh-tw/index.html",
    "JX": "https://www.starlux-airlines.com/zh-TW",
    "CX": "https://www.cathaypacific.com/cx/zh_TW.html",
    "IT": "https://www.tigerairtw.com/zh-tw/",
    "MM": "https://www.flypeach.com/tw",
    "JL": "https://www.jal.co.jp/tw/zhtw/",
    "NH": "https://www.ana.co.jp/zh/tw/",
    "KE": "https://www.koreanair.com/tw/zh",
    "OZ": "https://flyasiana.com/C/TW/ZHT/index",
    "TR": "https://www.flyscoot.com/zhtw",
    "SL": "https://www.lionairthai.com/tw/",
}


def _channel_comparison(item: dict[str, Any]) -> list[dict[str, Any]]:
    out_no = str((item.get("outbound") or {}).get("flight_number") or "")
    prefix = out_no[:2].upper() if len(out_no) >= 2 else ""
    airline_zh = _airline_zh(item.get("airline"), out_no)
    official_url = AIRLINE_OFFICIAL_URLS.get(prefix, "https://www.google.com/travel/flights")
    is_lcc = prefix in {"IT", "MM", "TR", "D7", "FD", "GK", "SL", "VZ", "TW", "BX"}
    return [
        {
            "badge": "🥇 最推薦首選 · 官方直營",
            "title": f"{airline_zh}官網直營",
            "subtitle": "親子選位、兒童餐點與航變直簽保障最完整",
            "amount": None,
            "currency": "TWD",
            "url": official_url,
            "cta": f"前往{airline_zh}官網直訂 ➔",
            "recommended": True,
            "highlights": [
                "親子同行可於官網預選相鄰座位與管理訂位代號（PNR）",
                "廉價航空需另購餐點與選位；官網加購最透明" if is_lcc else "傳航支援預訂兒童專屬餐點（CHML）與免費托運行李額度",
                "遇颱風或航班異動可由航空公司官方櫃檯／客服直接改簽免收平台手續費",
                "票價與座位供應請以官網結帳頁最終確認金額為準",
            ],
        },
        {
            "badge": "國際 OTA 平台",
            "title": "Trip.com (攜程海外版)",
            "subtitle": "常有平台促銷折扣，惟選位與退改需經平台處理",
            "amount": None,
            "currency": "TWD",
            "url": "https://tw.trip.com/flights",
            "cta": "前往 Trip.com 比價 ➔",
            "recommended": False,
            "highlights": [
                "偶有信用卡或平台專屬促銷折扣碼可折抵票價",
                "部分票種受限於起飛前 48 小時開放線上報到時才可免費選位",
                "退票、改期或航變須透過 OTA 平台規則與客服辦理，可能加收平台服務費",
                "請確認搜尋相同日期與去回程班號，並核對兒童年齡與行李額度",
            ],
        },
        {
            "badge": "台灣在地旅行社",
            "title": "易遊網 ezTravel",
            "subtitle": "可開立台灣統一發票／代收轉付收據，支援台灣信用卡分期",
            "amount": None,
            "currency": "TWD",
            "url": "https://flight.eztravel.com.tw/",
            "cta": "前往易遊網查看 ➔",
            "recommended": False,
            "highlights": [
                "可開立台灣統一發票或旅行業代收轉付收據（支援報帳統編需求）",
                "提供台灣在地 24 小時中文客服與多家銀行信用卡分期付款彈性",
                "請確認相同日期與去回程班號之兒童票價、行李額度與退改票規定",
            ],
        },
    ]


def engine_status() -> dict[str, Any]:
    latest = _load_json(_NAGOYA_LATEST_JSON.read_text(encoding="utf-8"), {}) if _NAGOYA_LATEST_JSON.exists() else {}
    monitor_cfg = _load_json(_NAGOYA_MONITOR_JSON.read_text(encoding="utf-8"), {}) if _NAGOYA_MONITOR_JSON.exists() else {}
    quota = latest.get("quota_after") or latest.get("quota_before") or {}
    used = quota.get("usage")
    remaining = quota.get("remaining")
    renewal = quota.get("renewal_date")
    api_key = _get_serpapi_key()
    if api_key:
        try:
            acct = _serpapi_request({"api_key": api_key}, endpoint=_SERPAPI_ACCOUNT_URL, timeout=4)
            if isinstance(acct, dict) and acct.get("plan_searches_left") is not None:
                used = acct.get("this_month_usage", used)
                remaining = acct.get("plan_searches_left", remaining)
        except Exception:
            pass
    try:
        _client()
        ignav_active = True
    except Exception:
        ignav_active = False
    return {
        "checked_at": latest.get("checked_at"),
        "source": latest.get("source"),
        "serpapi_quota": {
            "used": int(used) if used is not None else None,
            "remaining": int(remaining) if remaining is not None else None,
            "total": (int(used) + int(remaining)) if used is not None and remaining is not None else None,
            "renewal_date": renewal,
        },
        "ignav_active": ignav_active,
        "serpapi_active": bool(api_key),
        "monitor_config": {
            "origin": monitor_cfg.get("origin"),
            "destination": monitor_cfg.get("destination"),
            "outbound_date": monitor_cfg.get("outbound_date"),
            "inbound_date": monitor_cfg.get("inbound_date"),
            "passengers": monitor_cfg.get("passengers"),
            "family_target_twd": monitor_cfg.get("family_target_twd"),
        },
    }


DEFAULT_PRICE_FRESHNESS_HOURS = 24


def price_freshness_hours() -> int:
    """Shared maximum age for P1 cache, P2 current prices, and P3 quotes."""
    try:
        value = int((load_settings().get("planner") or {}).get(
            "price_freshness_hours", DEFAULT_PRICE_FRESHNESS_HOURS,
        ))
    except (TypeError, ValueError):
        value = DEFAULT_PRICE_FRESHNESS_HOURS
    return max(1, min(168, value))


def update_price_freshness_hours(value: int, tracking_hours: int | None = None) -> dict[str, int]:
    if isinstance(value, bool) or not 1 <= int(value) <= 168:
        raise PlannerError("新鮮度請設定為 1 至 168 小時。")
    settings = load_settings()
    if tracking_hours is not None and (isinstance(tracking_hours, bool) or not 1 <= tracking_hours <= 168):
        raise PlannerError("追蹤頻率請設定為 1 至 168 小時。")
    settings.setdefault("planner", {})["price_freshness_hours"] = int(value)
    if tracking_hours is not None:
        settings["planner"]["tracking_interval_hours"] = tracking_hours
    save_settings(settings)
    return {"price_freshness_hours": price_freshness_hours(), "tracking_interval_hours": tracking_interval_hours()}


def _traveler_signature(travelers: dict[str, Any] | None) -> str:
    t = travelers or {}
    adults = int(t.get("adults", 1) or 1)
    ages = [
        int(c.get("age_at_departure") if isinstance(c, dict) else c)
        for c in (t.get("children") or [])
        if (c.get("age_at_departure") if isinstance(c, dict) else c) is not None
    ]
    return json.dumps({"adults": adults, "children_ages": ages}, separators=(",", ":"), sort_keys=True)


def _is_quote_fresh(
    timestamp_str: str | None,
    now: datetime | None = None,
    max_age_hours: int | None = None,
) -> bool:
    if not timestamp_str:
        return False
    raw = str(timestamp_str).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?", raw):
        raw = raw.replace(" ", "T") + "+00:00"
    elif raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ref = now or datetime.now(timezone.utc)
    age_seconds = (ref - dt).total_seconds()
    return 0 <= age_seconds <= (max_age_hours if max_age_hours is not None else price_freshness_hours()) * 3600


def _evaluate_quote_verification(
    *,
    amount: float | None,
    price_scope: str | None,
    url: str | None,
    separate_tickets: bool = False,
    flight_matched: bool = True,
    flight_mismatch_reason: str | None = None,
    pax_mismatch_reason: str | None = None,
    option_passengers: dict[str, Any] | None = None,
    travelers: dict[str, Any] | None = None,
    provider_adults: int = 1,
    provider_children: int = 0,
    has_infant: bool = False,
    checked_at: str | None = None,
    now: datetime | None = None,
) -> tuple[bool, str | None, str, str]:
    """Return (verified_party_total, unverified_reason, status, status_label)."""
    pax_total = provider_adults + provider_children
    t = travelers or {}
    raw_adults = int(t.get("adults", 1) or 1)
    raw_children = len(t.get("children") or [])

    if has_infant:
        return (
            False,
            "需先設定未滿 2 歲嬰兒為抱坐或佔位，才能取得符合旅客組成的整組報價。",
            "needs_infant_choice",
            "未驗證（含未滿 2 歲嬰兒）",
        )
    if not flight_matched:
        return (
            False,
            flight_mismatch_reason or "回傳之去回日期或班號與候選航班不符。",
            "flight_mismatch",
            "未驗證（航班日期或班號不符）",
        )
    if pax_mismatch_reason:
        return (
            False,
            pax_mismatch_reason,
            "passenger_mismatch",
            "未驗證（旅客組成不符）",
        )
    if isinstance(option_passengers, dict) and option_passengers.get("adults") is not None:
        try:
            opt_a = int(option_passengers.get("adults") or 0)
            opt_c = int(option_passengers.get("children") or 0)
            valid_pairs = {(provider_adults, provider_children), (raw_adults, raw_children)}
            if (opt_a, opt_c) not in valid_pairs:
                return (
                    False,
                    f"通路回傳旅客組成（{opt_a}大{opt_c}小）與本次旅客設定（{raw_adults}大{raw_children}小）不符。",
                    "passenger_mismatch",
                    "未驗證（旅客組成不符）",
                )
        except (TypeError, ValueError):
            return (
                False,
                "通路回傳之旅客人數格式無法驗證。",
                "passenger_mismatch",
                "未驗證（旅客組成未知）",
            )
    if separate_tickets:
        return (
            False,
            "此報價需分開購買單程／拆票，非單一完整來回訂位總價。",
            "separate_tickets",
            "未驗證（需拆票購買）",
        )
    has_valid_url = isinstance(url, str) and url.startswith("https://")
    if amount is None or not isinstance(amount, (int, float)) or amount <= 0:
        if has_valid_url:
            return (
                False,
                "未提供價格（僅提供訂票連結）。",
                "links_only",
                "未提供價格",
            )
        return (
            False,
            "未提供價格與可用訂票連結。",
            "unavailable",
            "未提供價格",
        )

    scope_raw = str(price_scope or "unknown").strip()
    s = scope_raw.lower()
    if s in ("", "unknown", "unverified", "estimate", "estimated"):
        return (
            False,
            "計價範圍未知（供應商未確認是否為本次旅客整組總價）。",
            "unverified_scope",
            "未驗證（計價範圍未知）",
        )
    if s in ("per_person", "per_adult", "adult", "single"):
        if not (pax_total == 1 and provider_adults == 1 and provider_children == 0):
            return (
                False,
                f"供應商僅回傳每人單價（{scope_raw}），不得推算 {pax_total} 人整組總價。",
                "per_person_only",
                "未驗證（僅每人單價）",
            )
    elif s.startswith("party_of_"):
        m = re.match(r"^party_of_(\d+)", s)
        if not m or int(m.group(1)) != pax_total:
            return (
                False,
                f"計價人數範圍（{scope_raw}）與本次旅客總人數（{pax_total} 人）不符。",
                "passenger_mismatch",
                "未驗證（計價人數不符）",
            )
    elif s in ("party_total", "family_total", "total") or s.startswith("family_total") or s.startswith("family_"):
        if ("2a2c" in s or "2大2小" in s) and (provider_adults, provider_children) != (2, 2) and (raw_adults, raw_children) != (2, 2):
            return (
                False,
                f"報價限定 2大2小家庭組成（{scope_raw}），與本次旅客組成不符。",
                "passenger_mismatch",
                "未驗證（旅客組成不符）",
            )
    else:
        return (
            False,
            f"供應商有回傳價格，但未說明是每人價或本次 {pax_total} 位旅客的整組總價；此金額僅供參考，不會用來判定最低通路或決選。",
            "unverified_scope",
            "未驗證（計價範圍未知）",
        )

    if not has_valid_url:
        return (
            False,
            "未提供可用訂票連結。",
            "link_unavailable",
            "未驗證（無訂票連結）",
        )

    if checked_at and not _is_quote_fresh(checked_at, now=now):
        return (
            False,
            f"報價查詢時間已超過 {price_freshness_hours()} 小時新鮮期，請重新即時查詢通路。",
            "stale_quote",
            f"已逾 {price_freshness_hours()} 小時新鮮期",
        )

    return True, None, "available", "已驗證整組總價"


def _match_serpapi_leg(
    raw_item: dict[str, Any],
    expected_no: str,
    expected_date: str,
    expected_dep_airport: str,
    expected_arr_airport: str,
) -> dict[str, Any] | None:
    if not isinstance(raw_item, dict):
        return None
    flights = raw_item.get("flights") or []
    if not isinstance(flights, list) or len(flights) != 1:
        return None
    seg = flights[0]
    if not isinstance(seg, dict):
        return None
    fno = _flight_no(seg.get("flight_number"))
    if fno != expected_no:
        return None
    dep_airport = seg.get("departure_airport") or {}
    arr_airport = seg.get("arrival_airport") or {}
    if dep_airport.get("id") and str(dep_airport.get("id")).strip().upper() != expected_dep_airport:
        return None
    if arr_airport.get("id") and str(arr_airport.get("id")).strip().upper() != expected_arr_airport:
        return None
    dep_time_str = str(dep_airport.get("time") or seg.get("departure_time") or "").strip()
    date_match = re.match(r"^(\d{4}-\d{2}-\d{2})", dep_time_str)
    if date_match and date_match.group(1) != expected_date:
        return None
    item_date = str(raw_item.get("date") or raw_item.get("departure_date") or "").strip()[:10]
    if item_date and item_date != expected_date:
        return None
    return seg


def _extract_leg_date(raw_offer: dict[str, Any], leg_dict: dict[str, Any], direction: str) -> str | None:
    candidates = [
        raw_offer.get("outbound_date" if direction == "outbound" else "return_date"),
        raw_offer.get("departure_date" if direction == "outbound" else "inbound_date"),
        leg_dict.get("date"),
        leg_dict.get("flight_date"),
        leg_dict.get("departure_time_local"),
        leg_dict.get("departure_time"),
        leg_dict.get("departure"),
    ]
    segments = leg_dict.get("segments") or leg_dict.get("flights") or []
    if isinstance(segments, list) and segments and isinstance(segments[0], dict):
        first = segments[0]
        candidates.extend([
            first.get("date"),
            first.get("departure_time_local"),
            first.get("departure_time"),
            first.get("departure"),
            (first.get("departure_airport") or {}).get("time") if isinstance(first.get("departure_airport"), dict) else None,
        ])
    for c in candidates:
        if not c:
            continue
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", str(c).strip())
        if m:
            return m.group(1)
    return None


def _offer_matches_exact_candidate(raw: dict[str, Any], item: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Strictly verify that a provider offer matches candidate's origin, destination, outbound/return dates, and nonstop flight numbers."""
    if not isinstance(raw, dict):
        return None, "回傳格式不正確"
    origin = item["origin"]
    destination = item["destination"]
    outbound_date = item["outbound_date"]
    return_date = item["return_date"]
    out_no = _flight_no((item.get("outbound") or {}).get("flight_number"))
    in_no = _flight_no((item.get("inbound") or {}).get("flight_number"))

    if raw.get("origin") and str(raw.get("origin")).strip().upper() != origin:
        return None, "出發地不符"
    if raw.get("destination") and str(raw.get("destination")).strip().upper() != destination:
        return None, "目的地不符"

    out_raw_leg = raw.get("outbound") or raw.get("legs", {}).get("outbound") or {}
    in_raw_leg = raw.get("inbound") or raw.get("legs", {}).get("inbound") or {}
    raw_out_date = _extract_leg_date(raw, out_raw_leg if isinstance(out_raw_leg, dict) else {}, "outbound")
    raw_in_date = _extract_leg_date(raw, in_raw_leg if isinstance(in_raw_leg, dict) else {}, "inbound")
    if raw_out_date and raw_out_date != outbound_date:
        return None, f"去程日期不符（回傳 {raw_out_date}，候選為 {outbound_date}）"
    if raw_in_date and raw_in_date != return_date:
        return None, f"回程日期不符（回傳 {raw_in_date}，候選為 {return_date}）"

    parsed = _itinerary(raw, origin, destination, outbound_date, return_date)
    if parsed["outbound"].get("stops") or parsed["inbound"].get("stops"):
        return None, "非直飛航班"
    if _flight_no(parsed["outbound"].get("flight_number")) != out_no:
        return None, f"去程班號不符（回傳 {parsed['outbound'].get('flight_number')}，候選為 {out_no}）"
    if _flight_no(parsed["inbound"].get("flight_number")) != in_no:
        return None, f"回程班號不符（回傳 {parsed['inbound'].get('flight_number')}，候選為 {in_no}）"
    return parsed, None


def _check_option_flight_match(option: dict[str, Any], normalized: dict[str, Any], item: dict[str, Any]) -> tuple[bool, str | None]:
    out_no = _flight_no((item.get("outbound") or {}).get("flight_number"))
    in_no = _flight_no((item.get("inbound") or {}).get("flight_number"))
    outbound_date = item["outbound_date"]
    return_date = item["return_date"]

    for src in (normalized, option):
        if not isinstance(src, dict):
            continue
        opt_out_date = str(src.get("outbound_date") or src.get("departure_date") or "")[:10]
        if opt_out_date and opt_out_date != outbound_date:
            return False, f"通路回傳去程日期（{opt_out_date}）與候選（{outbound_date}）不符。"
        opt_in_date = str(src.get("return_date") or src.get("inbound_date") or "")[:10]
        if opt_in_date and opt_in_date != return_date:
            return False, f"通路回傳回程日期（{opt_in_date}）與候選（{return_date}）不符。"
        opt_out_no = _flight_no(src.get("outbound_flight") or src.get("outbound_flight_number"))
        if opt_out_no and opt_out_no != out_no:
            return False, f"通路回傳去程班號（{opt_out_no}）與候選（{out_no}）不符。"
        opt_in_no = _flight_no(src.get("inbound_flight") or src.get("inbound_flight_number"))
        if opt_in_no and opt_in_no != in_no:
            return False, f"通路回傳回程班號（{opt_in_no}）與候選（{in_no}）不符。"
        marketed = src.get("marketed_as")
        if isinstance(marketed, list) and marketed:
            marketed_nos = [_flight_no(m) for m in marketed if _flight_no(m)]
            if marketed_nos and marketed_nos != [out_no, in_no]:
                return False, f"通路回傳班號組合（{'/'.join(marketed_nos)}）與候選（{out_no}/{in_no}）不符。"
    return True, None


def _summarize_api_source(
    api_source: str,
    label: str,
    checked_at: str,
    quotes: list[dict[str, Any]],
    fallback_status: str = "unavailable",
    fallback_status_label: str = "尚未查詢",
    fallback_reason: str | None = None,
    fallback_url: str | None = None,
    fallback_amount: float | None = None,
    fallback_scope: str = "unknown",
) -> dict[str, Any]:
    verified = [q for q in quotes if q.get("verified_party_total")]
    if verified:
        best = min(verified, key=lambda q: float(q["amount"]))
        return {
            "api_source": api_source,
            "label": label,
            "provider": best.get("provider") or label,
            "amount": best["amount"],
            "currency": best.get("currency") or "TWD",
            "price_scope": best.get("price_scope") or "party_total",
            "status": "available",
            "status_label": "已驗證整組總價",
            "checked_at": checked_at,
            "url": best.get("url"),
            "verified_party_total": True,
            "unverified_reason": None,
            "is_fresh": _is_quote_fresh(checked_at),
            "quotes": quotes,
        }
    if quotes:
        priced = [q for q in quotes if q.get("amount") is not None]
        rep = priced[0] if priced else quotes[0]
        return {
            "api_source": api_source,
            "label": label,
            "provider": rep.get("provider") or label,
            "amount": rep.get("amount") if rep.get("amount") is not None else fallback_amount,
            "currency": rep.get("currency") or "TWD",
            "price_scope": rep.get("price_scope") or fallback_scope,
            "status": rep.get("status") or fallback_status,
            "status_label": rep.get("status_label") or fallback_status_label,
            "checked_at": checked_at,
            "url": rep.get("url") or fallback_url,
            "verified_party_total": False,
            "unverified_reason": rep.get("unverified_reason") or fallback_reason,
            "is_fresh": _is_quote_fresh(checked_at),
            "quotes": quotes,
        }
    return {
        "api_source": api_source,
        "label": label,
        "provider": label,
        "amount": fallback_amount,
        "currency": "TWD",
        "price_scope": fallback_scope,
        "status": fallback_status,
        "status_label": fallback_status_label,
        "checked_at": checked_at,
        "url": fallback_url,
        "verified_party_total": False,
        "unverified_reason": fallback_reason,
        "is_fresh": _is_quote_fresh(checked_at),
        "quotes": [],
    }


def _p3_query_serpapi(
    item: dict[str, Any],
    travelers: dict[str, Any],
    adults: int,
    children: int,
    has_infant: bool,
    checked_at: str,
) -> dict[str, Any]:
    label = "SerpApi (Google Flights)"
    origin = item["origin"]
    destination = item["destination"]
    outbound_date = item["outbound_date"]
    return_date = item["return_date"]
    out_no = _flight_no((item.get("outbound") or {}).get("flight_number"))
    in_no = _flight_no((item.get("inbound") or {}).get("flight_number"))
    pax_total = adults + children

    if has_infant:
        return _summarize_api_source(
            "serpapi", label, checked_at, [],
            fallback_status="needs_infant_choice",
            fallback_status_label="未驗證（含未滿 2 歲嬰兒）",
            fallback_reason="需先設定未滿 2 歲嬰兒為抱坐或佔位，才能取得符合旅客組成的整組報價。",
        )

    api_key = _get_serpapi_key()
    if not api_key:
        return _summarize_api_source(
            "serpapi", label, checked_at, [],
            fallback_status="provider_unavailable",
            fallback_status_label="未設定 SerpApi 金鑰",
            fallback_reason="尚未設定 SERPAPI_KEY，無法向 SerpApi 即時查價。",
        )

    base_params: dict[str, Any] = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "type": 1,
        "travel_class": 1,
        "adults": adults,
        "children": children,
        "stops": 1,
        "currency": "TWD",
        "gl": "tw",
        "hl": "zh-TW",
        "api_key": api_key,
    }

    try:
        market_data = _serpapi_request(base_params)
    except Exception:
        return _summarize_api_source(
            "serpapi", label, checked_at, [],
            fallback_status="provider_lookup_failed",
            fallback_status_label="SerpApi 查詢失敗",
            fallback_reason="SerpApi Google Flights 即時連線或查詢失敗。",
        )

    if not isinstance(market_data, dict):
        return _summarize_api_source(
            "serpapi", label, checked_at, [],
            fallback_status="provider_lookup_failed",
            fallback_status_label="SerpApi 回應無效",
            fallback_reason="SerpApi 未回傳有效 JSON 資料。",
        )

    metadata_url = (market_data.get("search_metadata") or {}).get("google_flights_url")
    if not (isinstance(metadata_url, str) and metadata_url.startswith("https://")):
        metadata_url = None

    echoed = market_data.get("search_parameters") or {}
    pax_mismatch_reason = None
    if isinstance(echoed, dict):
        if ("adults" in echoed and int(echoed["adults"]) != adults) or (
            "children" in echoed and int(echoed.get("children") or 0) != children
        ):
            pax_mismatch_reason = (
                f"SerpApi 回傳旅客參數（{echoed.get('adults')}大{echoed.get('children', 0)}小）"
                f"與本次查詢條件（{adults}位成人級距、{children}位兒童級距）不符。"
            )

    matched_out_item: dict[str, Any] | None = None
    for raw_item in [*(market_data.get("best_flights") or []), *(market_data.get("other_flights") or [])]:
        if _match_serpapi_leg(raw_item, out_no, outbound_date, origin, destination):
            matched_out_item = raw_item
            break

    if not matched_out_item:
        return _summarize_api_source(
            "serpapi", label, checked_at, [],
            fallback_status="missing_provider_offer",
            fallback_status_label="未配對相符去程航班",
            fallback_reason=f"SerpApi 未回傳 {outbound_date} {out_no} 直飛去程航班。",
            fallback_url=metadata_url,
        )

    dep_token = matched_out_item.get("departure_token")
    ret_data: dict[str, Any] | None = None
    if dep_token:
        try:
            ret_data = _serpapi_request({**base_params, "departure_token": dep_token})
        except Exception:
            return _summarize_api_source(
                "serpapi", label, checked_at, [],
                fallback_status="provider_lookup_failed",
                fallback_status_label="SerpApi 回程查詢失敗",
                fallback_reason=f"SerpApi 展開 {out_no} 回程航班時查詢失敗。",
                fallback_url=metadata_url,
            )
    elif isinstance(matched_out_item.get("return_flights"), list):
        ret_data = {"best_flights": matched_out_item["return_flights"]}

    if not isinstance(ret_data, dict):
        out_amt, _ = _money(matched_out_item)
        return _summarize_api_source(
            "serpapi", label, checked_at, [],
            fallback_status="missing_provider_offer",
            fallback_status_label="缺少實際回程配對",
            fallback_reason=f"SerpApi 僅回傳去程 {out_no}，無 departure_token 可驗證 {return_date} {in_no} 回程（P3 禁止以已知班表推估）。",
            fallback_url=metadata_url,
            fallback_amount=out_amt,
            fallback_scope="unknown",
        )

    ret_meta_url = (ret_data.get("search_metadata") or {}).get("google_flights_url")
    if isinstance(ret_meta_url, str) and ret_meta_url.startswith("https://"):
        metadata_url = ret_meta_url

    ret_echoed = ret_data.get("search_parameters") or {}
    if isinstance(ret_echoed, dict) and not pax_mismatch_reason:
        if ("adults" in ret_echoed and int(ret_echoed["adults"]) != adults) or (
            "children" in ret_echoed and int(ret_echoed.get("children") or 0) != children
        ):
            pax_mismatch_reason = (
                f"SerpApi 回程旅客參數（{ret_echoed.get('adults')}大{ret_echoed.get('children', 0)}小）"
                f"與本次查詢條件（{adults}位成人級距、{children}位兒童級距）不符。"
            )

    matched_ret_item: dict[str, Any] | None = None
    for r_item in [*(ret_data.get("best_flights") or []), *(ret_data.get("other_flights") or [])]:
        if _match_serpapi_leg(r_item, in_no, return_date, destination, origin):
            matched_ret_item = r_item
            break

    if not matched_ret_item:
        return _summarize_api_source(
            "serpapi", label, checked_at, [],
            fallback_status="missing_provider_offer",
            fallback_status_label="未配對相符回程航班",
            fallback_reason=f"SerpApi 已配對去程 {outbound_date} {out_no}，但未回傳 {return_date} {in_no} 直飛回程航班。",
            fallback_url=metadata_url,
        )

    booking_data: dict[str, Any] | None = None
    if not matched_ret_item.get("booking_token") and isinstance(ret_data.get("booking_options"), list) and ret_data.get("booking_options"):
        booking_data = ret_data
    elif matched_ret_item.get("booking_token"):
        try:
            b_resp = _serpapi_request({**base_params, "booking_token": matched_ret_item["booking_token"]})
            if isinstance(b_resp, dict):
                booking_data = b_resp
                b_meta_url = (b_resp.get("search_metadata") or {}).get("google_flights_url")
                if isinstance(b_meta_url, str) and b_meta_url.startswith("https://"):
                    metadata_url = b_meta_url
        except Exception:
            booking_data = None

    quotes: list[dict[str, Any]] = []
    raw_booking_options = (booking_data.get("booking_options") if isinstance(booking_data, dict) else None) or []
    booking_echo = (booking_data or {}).get("search_parameters") or {}
    selected = (booking_data or {}).get("selected_flights") or []
    party_context_confirmed = (
        isinstance(booking_echo, dict)
        and str(booking_echo.get("adults")) == str(adults)
        and str(booking_echo.get("children")) == str(children)
        and str(booking_echo.get("type")) == "1"
        and isinstance(selected, list) and len(selected) == 2
        and bool(_match_serpapi_leg(selected[0], out_no, outbound_date, origin, destination))
        and bool(_match_serpapi_leg(selected[1], in_no, return_date, destination, origin))
    )
    if isinstance(raw_booking_options, list) and raw_booking_options:
        for raw_opt in raw_booking_options:
            if not isinstance(raw_opt, dict):
                continue
            together = raw_opt.get("together") if isinstance(raw_opt.get("together"), dict) else None
            norm = together or raw_opt
            flight_ok, flight_err = _check_option_flight_match(raw_opt, norm, item)
            if not flight_ok:
                # A different itinerary is not a channel quote for this candidate.
                continue
            separate = bool(raw_opt.get("separate_tickets", False) or norm.get("separate_tickets", False))
            amount, currency = _money(norm)
            if amount is None and raw_opt.get("displayed_price_twd") is not None:
                try:
                    amount, currency = _to_twd(float(raw_opt["displayed_price_twd"]), "TWD")
                except (TypeError, ValueError):
                    pass
            raw_scope = norm.get("price_scope") or raw_opt.get("price_scope")
            # Google Flights uses the echoed party and selected round trip, not price_scope.
            if raw_scope is None and together and party_context_confirmed and not pax_mismatch_reason:
                raw_scope = "party_total"
            if raw_scope is None:
                raw_scope = "unknown"
            raw_url = (
                norm.get("url")
                or norm.get("booking_url")
                or raw_opt.get("url")
                or raw_opt.get("booking_url")
                or (norm.get("booking_request") or {}).get("url")
                or (raw_opt.get("booking_request") or {}).get("url")
                or metadata_url
            )
            url = raw_url if isinstance(raw_url, str) and raw_url.startswith("https://") else None
            book_with = norm.get("book_with") or norm.get("provider") or raw_opt.get("provider") or "Google Flights"
            provider_name = book_with if str(book_with).startswith("SerpApi") else f"SerpApi · {book_with}"
            baggage_prices = norm.get("baggage_prices") or raw_opt.get("baggage_prices")
            terms = norm.get("terms") or norm.get("conditions") or raw_opt.get("terms") or raw_opt.get("conditions")
            if not terms and isinstance(baggage_prices, list) and baggage_prices:
                terms = " / ".join(str(x) for x in baggage_prices if x)
            if isinstance(terms, (dict, list)):
                terms = json.dumps(terms, ensure_ascii=False)
            passenger_fares = norm.get("passenger_fares") or raw_opt.get("passenger_fares")
            opt_passengers = norm.get("passengers") or raw_opt.get("passengers")

            verified, reason, st, st_label = _evaluate_quote_verification(
                amount=amount,
                price_scope=raw_scope,
                url=url,
                separate_tickets=separate,
                flight_matched=flight_ok,
                flight_mismatch_reason=flight_err,
                pax_mismatch_reason=pax_mismatch_reason,
                option_passengers=opt_passengers if isinstance(opt_passengers, dict) else None,
                travelers=travelers,
                provider_adults=adults,
                provider_children=children,
                has_infant=has_infant,
                checked_at=checked_at,
            )
            quotes.append({
                "api_source": "serpapi",
                "provider": provider_name,
                "amount": amount,
                "currency": currency or "TWD",
                "price_scope": raw_scope,
                "url": url,
                "status": st,
                "status_label": st_label,
                "terms": terms,
                "passenger_fares": passenger_fares if isinstance(passenger_fares, list) else None,
                "separate_tickets": separate,
                "verified_party_total": verified,
                "unverified_reason": reason,
                "observed_at": checked_at,
                "is_fresh": True,
            })
    else:
        flight_ok, flight_err = _check_option_flight_match(matched_ret_item, matched_ret_item, item)
        separate = bool(matched_ret_item.get("separate_tickets", False))
        amount, currency = _money(matched_ret_item)
        raw_scope = matched_ret_item.get("price_scope")
        if raw_scope is None:
            raw_scope = "unknown"
        raw_url = (
            matched_ret_item.get("url")
            or matched_ret_item.get("booking_url")
            or (matched_ret_item.get("booking_request") or {}).get("url")
            or metadata_url
        )
        url = raw_url if isinstance(raw_url, str) and raw_url.startswith("https://") else None
        terms = matched_ret_item.get("terms") or _format_bags(matched_ret_item.get("bags"))
        if isinstance(terms, (dict, list)):
            terms = json.dumps(terms, ensure_ascii=False)
        passenger_fares = matched_ret_item.get("passenger_fares")
        opt_passengers = matched_ret_item.get("passengers")

        verified, reason, st, st_label = _evaluate_quote_verification(
            amount=amount,
            price_scope=raw_scope,
            url=url,
            separate_tickets=separate,
            flight_matched=flight_ok,
            flight_mismatch_reason=flight_err,
            pax_mismatch_reason=pax_mismatch_reason,
            option_passengers=opt_passengers if isinstance(opt_passengers, dict) else None,
            travelers=travelers,
            provider_adults=adults,
            provider_children=children,
            has_infant=has_infant,
            checked_at=checked_at,
        )
        quotes.append({
            "api_source": "serpapi",
            "provider": label,
            "amount": amount,
            "currency": currency or "TWD",
            "price_scope": raw_scope,
            "url": url,
            "status": st,
            "status_label": st_label,
            "terms": terms,
            "passenger_fares": passenger_fares if isinstance(passenger_fares, list) else None,
            "separate_tickets": separate,
            "verified_party_total": verified,
            "unverified_reason": reason,
            "observed_at": checked_at,
            "is_fresh": True,
        })

    return _summarize_api_source("serpapi", label, checked_at, quotes, fallback_url=metadata_url)


def _p3_query_ignav(
    item: dict[str, Any],
    travelers: dict[str, Any],
    adults: int,
    children: int,
    has_infant: bool,
    checked_at: str,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    label = "Ignav"
    origin = item["origin"]
    destination = item["destination"]
    outbound_date = item["outbound_date"]
    return_date = item["return_date"]
    out_no = _flight_no((item.get("outbound") or {}).get("flight_number"))
    in_no = _flight_no((item.get("inbound") or {}).get("flight_number"))

    if has_infant:
        return _summarize_api_source(
            "ignav", label, checked_at, [],
            fallback_status="needs_infant_choice",
            fallback_status_label="未驗證（含未滿 2 歲嬰兒）",
            fallback_reason="需先設定未滿 2 歲嬰兒為抱坐或佔位，才能取得符合旅客組成的整組報價。",
        )

    try:
        client, ignav_error = _client()
    except PlannerError as exc:
        return _summarize_api_source(
            "ignav", label, checked_at, [],
            fallback_status="provider_unavailable",
            fallback_status_label="未設定 Ignav 金鑰",
            fallback_reason=str(exc),
        )

    try:
        search = client.search_round_trip(
            origin=origin,
            destination=destination,
            departure_date=outbound_date,
            return_date=return_date,
            adults=adults,
            children=children,
            currency="TWD",
        )
    except Exception:
        return _summarize_api_source(
            "ignav", label, checked_at, [],
            fallback_status="provider_lookup_failed",
            fallback_status_label="Ignav 航班查詢失敗",
            fallback_reason="Ignav 即時航班比對查詢失敗，請稍後重試。",
        )

    provider_observed_at = search.get("observed_at") if isinstance(search, dict) else None
    matched_offer: dict[str, Any] | None = None
    matched_raw: dict[str, Any] | None = None
    mismatch_reasons: list[str] = []

    if isinstance(search, dict):
        for raw in _offers(search):
            parsed, err = _offer_matches_exact_candidate(raw, item)
            if parsed is not None:
                matched_offer = parsed
                matched_raw = raw
                break
            if err:
                mismatch_reasons.append(err)
        if not matched_offer:
            detail = f"（{mismatch_reasons[0]}）" if mismatch_reasons else ""
            return _summarize_api_source(
                "ignav", label, checked_at, [],
                fallback_status="missing_provider_offer",
                fallback_status_label="未配對相符去回航班",
                fallback_reason=f"Ignav 未回傳 {outbound_date} {out_no} ⇄ {return_date} {in_no} 的相符直飛航班{detail}。",
            )
        ignav_id = matched_offer.get("ignav_id") or item.get("ignav_id")
        if matched_offer.get("ignav_id") and matched_offer.get("ignav_id") != item.get("ignav_id"):
            item["ignav_id"] = matched_offer["ignav_id"]
            if candidate_id:
                with _connection() as conn:
                    row = conn.execute("SELECT payload_json FROM planner_candidates WHERE id=?", (candidate_id,)).fetchone()
                    if row:
                        stored_item = _load_json(row["payload_json"], {})
                        stored_item["ignav_id"] = matched_offer["ignav_id"]
                        conn.execute(
                            "UPDATE planner_candidates SET payload_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            (json.dumps(stored_item, ensure_ascii=False), candidate_id),
                        )
    else:
        ignav_id = item.get("ignav_id")

    search_amount = matched_offer.get("amount") if matched_offer else None
    search_scope = matched_offer.get("price_scope", "unknown") if matched_offer else "unknown"
    search_url = (matched_raw.get("url") or matched_raw.get("booking_url")) if isinstance(matched_raw, dict) else None
    if not (isinstance(search_url, str) and search_url.startswith("https://")):
        search_url = None

    if not ignav_id:
        quotes: list[dict[str, Any]] = []
        if matched_offer and (search_amount is not None or search_url):
            opt_passengers = matched_raw.get("passengers") if isinstance(matched_raw, dict) else None
            verified, reason, st, st_label = _evaluate_quote_verification(
                amount=search_amount,
                price_scope=search_scope,
                url=search_url,
                separate_tickets=bool(matched_offer.get("requires_self_transfer", False)),
                flight_matched=True,
                option_passengers=opt_passengers if isinstance(opt_passengers, dict) else None,
                travelers=travelers,
                provider_adults=adults,
                provider_children=children,
                has_infant=has_infant,
                checked_at=provider_observed_at or checked_at,
            )
            quotes.append({
                "api_source": "ignav",
                "provider": "Ignav",
                "amount": search_amount,
                "currency": matched_offer.get("currency") or "TWD",
                "price_scope": search_scope,
                "url": search_url,
                "status": st,
                "status_label": st_label,
                "terms": matched_offer.get("bags"),
                "passenger_fares": None,
                "separate_tickets": False,
                "verified_party_total": verified,
                "unverified_reason": reason,
                "observed_at": provider_observed_at or checked_at,
                "is_fresh": _is_quote_fresh(provider_observed_at or checked_at),
            })
        return _summarize_api_source(
            "ignav", label, checked_at, quotes,
            fallback_status="missing_provider_offer",
            fallback_status_label="缺少 Ignav 識別碼",
            fallback_reason="Ignav 未提供此航班之 ignav_id 與訂票連結。",
            fallback_amount=search_amount,
            fallback_scope=search_scope,
            fallback_url=search_url,
        )

    try:
        payload = client.get_booking_links(ignav_id)
    except Exception:
        return _summarize_api_source(
            "ignav", label, checked_at, [],
            fallback_status="provider_lookup_failed",
            fallback_status_label="Ignav 訂票連結查詢失敗",
            fallback_reason="Ignav get_booking_links 查詢失敗，請稍後重試。",
            fallback_amount=search_amount,
            fallback_scope=search_scope,
            fallback_url=search_url,
        )

    groups = (payload.get("booking_options") if isinstance(payload, dict) else None) or []
    provider_observed_at = (payload.get("observed_at") if isinstance(payload, dict) else None) or provider_observed_at
    options = []
    for group in groups:
        if isinstance(group, dict) and isinstance(group.get("links"), list):
            for link in group["links"]:
                if isinstance(link, dict):
                    options.append({**group, **link, "provider": link.get("provider_name") or link.get("provider")})
        else:
            options.append(group)
    quotes = []
    for option in options:
        if not isinstance(option, dict):
            continue
        together = option.get("together") if isinstance(option.get("together"), dict) else None
        normalized = together or option
        flight_ok, flight_err = _check_option_flight_match(option, normalized, item)
        amount, currency = _money(normalized)
        if amount is None and option.get("displayed_price_twd") is not None:
            try:
                amount, currency = _to_twd(float(option["displayed_price_twd"]), "TWD")
            except (TypeError, ValueError):
                pass
        raw_url = normalized.get("url") or normalized.get("booking_url") or option.get("url") or option.get("booking_url")
        url = raw_url if isinstance(raw_url, str) and raw_url.startswith("https://") else None
        terms = normalized.get("terms") or normalized.get("conditions") or option.get("terms") or option.get("conditions")
        if isinstance(terms, (dict, list)):
            terms = json.dumps(terms, ensure_ascii=False)
        passenger_fares = normalized.get("passenger_fares") or option.get("passenger_fares")
        price_scope = normalized.get("price_scope") or option.get("price_scope") or "unknown"
        separate = bool(option.get("separate_tickets", False) or normalized.get("separate_tickets", False))
        opt_passengers = normalized.get("passengers") or option.get("passengers")
        if not isinstance(opt_passengers, dict) and isinstance(payload, dict):
            opt_passengers = payload.get("passengers")

        verified, reason, st, st_label = _evaluate_quote_verification(
            amount=amount,
            price_scope=price_scope,
            url=url,
            separate_tickets=separate,
            flight_matched=flight_ok,
            flight_mismatch_reason=flight_err,
            option_passengers=opt_passengers if isinstance(opt_passengers, dict) else None,
            travelers=travelers,
            provider_adults=adults,
            provider_children=children,
            has_infant=has_infant,
            checked_at=provider_observed_at or checked_at,
        )
        quotes.append({
            "api_source": "ignav",
            "provider": normalized.get("provider") or normalized.get("book_with") or option.get("provider") or "Ignav 訂票通路",
            "amount": amount,
            "currency": currency or "TWD",
            "price_scope": price_scope,
            "url": url,
            "status": st,
            "status_label": st_label,
            "terms": terms,
            "passenger_fares": passenger_fares if isinstance(passenger_fares, list) else None,
            "separate_tickets": separate,
            "verified_party_total": verified,
            "unverified_reason": reason,
            "observed_at": provider_observed_at or checked_at,
            "is_fresh": _is_quote_fresh(provider_observed_at or checked_at),
        })

    if not quotes and matched_offer and (search_amount is not None or search_url):
        opt_passengers = matched_raw.get("passengers") if isinstance(matched_raw, dict) else None
        verified, reason, st, st_label = _evaluate_quote_verification(
            amount=search_amount,
            price_scope=search_scope,
            url=search_url,
            separate_tickets=bool(matched_offer.get("requires_self_transfer", False)),
            flight_matched=True,
            option_passengers=opt_passengers if isinstance(opt_passengers, dict) else None,
            travelers=travelers,
            provider_adults=adults,
            provider_children=children,
            has_infant=has_infant,
            checked_at=provider_observed_at or checked_at,
        )
        quotes.append({
            "api_source": "ignav",
            "provider": "Ignav",
            "amount": search_amount,
            "currency": matched_offer.get("currency") or "TWD",
            "price_scope": search_scope,
            "url": search_url,
            "status": st,
            "status_label": st_label,
            "terms": matched_offer.get("bags"),
            "passenger_fares": None,
            "separate_tickets": False,
            "verified_party_total": verified,
            "unverified_reason": reason,
            "observed_at": provider_observed_at or checked_at,
            "is_fresh": _is_quote_fresh(provider_observed_at or checked_at),
        })

    return _summarize_api_source(
        "ignav", label, checked_at, quotes,
        fallback_status="no_booking_options",
        fallback_status_label="無可用訂票通路",
        fallback_reason="Ignav 目前沒有回傳可用訂票通路。",
        fallback_amount=search_amount,
        fallback_scope=search_scope,
        fallback_url=search_url,
    )


def _derive_overall_p3_status(
    serp_source: dict[str, Any],
    ignav_source: dict[str, Any],
    booking_options: list[dict[str, Any]],
    has_infant: bool,
) -> tuple[str, str]:
    if has_infant:
        return (
            "needs_infant_choice",
            "需先設定未滿 2 歲嬰兒為抱坐或佔位，才能取得符合旅客組成的報價。",
        )
    verified_options = [opt for opt in booking_options if opt.get("verified_party_total") and opt.get("is_fresh", True)]
    if verified_options:
        return (
            "ready",
            f"已取得 {len(verified_options)} 組通過本次旅客組成驗證之整組總價與訂票連結，可進行最終決選。",
        )

    stale_options = [opt for opt in booking_options if opt.get("status") == "stale_quote"]
    if stale_options:
        return (
            "stale_quotes",
            f"通路報價已超過 {price_freshness_hours()} 小時新鮮期，請重新查詢通路以取得最新即時報價。",
        )

    priced_options = [opt for opt in booking_options if opt.get("amount") is not None]
    if priced_options:
        reasons = []
        for opt in priced_options:
            if opt.get("unverified_reason") and opt["unverified_reason"] not in reasons:
                reasons.append(opt["unverified_reason"])
        reason_text = "；".join(reasons[:2]) if reasons else "未確認為本次旅客整組總價或缺少訂票連結。"
        return (
            "unverified_quotes",
            f"已取得報價但未通過決選驗證：{reason_text}（保留為未驗證資料，不可直接決選）。",
        )

    if booking_options:
        return (
            "links_only",
            "供應商有回傳訂票通路連結，但未提供價格；請點選連結查看即時票價（未驗證整組總價前不可決選）。",
        )

    statuses = {serp_source.get("status"), ignav_source.get("status")}
    if statuses == {"provider_unavailable"}:
        return (
            "provider_unavailable",
            ignav_source.get("unverified_reason") or serp_source.get("unverified_reason") or "雙引擎 API 金鑰皆未設定。",
        )
    if "provider_lookup_failed" in statuses and not ("missing_provider_offer" in statuses or "no_booking_options" in statuses):
        return (
            "provider_lookup_failed",
            "即時查價連線失敗，請稍後重試；目前仍可參考各大購票管道入口。",
        )
    if "missing_provider_offer" in statuses:
        return (
            "missing_provider_offer",
            "SerpApi 與 Ignav 目前皆未回傳完全相符的去回日期與班號；可使用各大購票管道入口自行查價。",
        )
    return (
        "no_booking_options",
        "供應商目前沒有回傳可用訂票通路與報價；請參考各大購票管道選購指南。",
    )


@operation("P3")
def _execute_p3_dual_lookup(
    candidate_id: str,
    item: dict[str, Any],
    travelers: dict[str, Any],
    adults: int,
    children: int,
    has_infant: bool,
) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat()
    traveler_sig = _traveler_signature(travelers)

    serp_source = _p3_query_serpapi(item, travelers, adults, children, has_infant, checked_at)
    ignav_source = _p3_query_ignav(item, travelers, adults, children, has_infant, checked_at, candidate_id=candidate_id)

    booking_options: list[dict[str, Any]] = [
        *serp_source.get("quotes", []),
        *ignav_source.get("quotes", []),
    ]
    status, message = _derive_overall_p3_status(serp_source, ignav_source, booking_options, has_infant)
    api_sources = {
        "serpapi": {k: v for k, v in serp_source.items() if k != "quotes"},
        "ignav": {k: v for k, v in ignav_source.items() if k != "quotes"},
    }

    if not has_infant:
        with _connection() as conn:
            conn.execute("DELETE FROM planner_booking_quotes WHERE candidate_id=?", (candidate_id,))
            for option in booking_options:
                conn.execute(
                    "INSERT INTO planner_booking_quotes("
                    "candidate_id,api_source,provider,amount,currency,price_scope,booking_url,"
                    "status,terms,passenger_fares_json,separate_tickets,verified_party_total,"
                    "unverified_reason,traveler_signature,observed_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        candidate_id,
                        option.get("api_source"),
                        option["provider"],
                        option["amount"],
                        option["currency"],
                        option["price_scope"],
                        option["url"],
                        option["status"],
                        option["terms"],
                        json.dumps(option["passenger_fares"], ensure_ascii=False) if option.get("passenger_fares") else None,
                        int(bool(option.get("separate_tickets", False))),
                        int(bool(option.get("verified_party_total", False))),
                        option.get("unverified_reason"),
                        traveler_sig,
                        option.get("observed_at") or checked_at,
                    ),
                )
            conn.execute(
                "INSERT INTO planner_p3_quote_runs(candidate_id,traveler_signature,api_sources_json,status,message,checked_at) "
                "VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(candidate_id) DO UPDATE SET "
                "traveler_signature=excluded.traveler_signature, "
                "api_sources_json=excluded.api_sources_json, "
                "status=excluded.status, "
                "message=excluded.message, "
                "checked_at=excluded.checked_at",
                (candidate_id, traveler_sig, json.dumps(api_sources, ensure_ascii=False), status, message, checked_at),
            )

    can_decide = any(opt.get("verified_party_total") and opt.get("is_fresh", True) for opt in booking_options)
    return {
        "candidate_id": candidate_id,
        "itinerary": item,
        "travelers": travelers,
        "provider_travelers": {"adults": adults, "children": children, "total": adults + children},
        "checked_at": checked_at,
        "freshness_hours": price_freshness_hours(),
        "is_fresh": True,
        "api_sources": api_sources,
        "booking_options": booking_options,
        "channel_comparison": _channel_comparison(item),
        "can_decide": can_decide,
        "decision_persisted": False,
        "status": status,
        "message": message,
    }


def _load_stored_p3_quotes(
    candidate_id: str,
    item: dict[str, Any],
    travelers: dict[str, Any],
    adults: int,
    children: int,
    has_infant: bool,
) -> dict[str, Any] | None:
    traveler_sig = _traveler_signature(travelers)
    with _connection() as conn:
        run_row = conn.execute(
            "SELECT * FROM planner_p3_quote_runs WHERE candidate_id=?",
            (candidate_id,),
        ).fetchone()
        quote_rows = conn.execute(
            "SELECT api_source,provider,amount,currency,price_scope,booking_url,status,terms,"
            "passenger_fares_json,separate_tickets,verified_party_total,unverified_reason,"
            "traveler_signature,observed_at "
            "FROM planner_booking_quotes WHERE candidate_id=? ORDER BY id ASC",
            (candidate_id,),
        ).fetchall()

    if not run_row and not quote_rows:
        return None
    if run_row and run_row["traveler_signature"] != traveler_sig:
        return None
    if quote_rows and any(r["traveler_signature"] and r["traveler_signature"] != traveler_sig for r in quote_rows):
        return None

    checked_at = run_row["checked_at"] if run_row else (quote_rows[0]["observed_at"] if quote_rows else None)
    run_is_fresh = _is_quote_fresh(checked_at)

    booking_options: list[dict[str, Any]] = []
    for r in quote_rows:
        q_dict = dict(r)
        url = q_dict.get("booking_url")
        obs_at = q_dict.get("observed_at") or checked_at
        verified, reason, st, st_label = _evaluate_quote_verification(
            amount=q_dict.get("amount"),
            price_scope=q_dict.get("price_scope"),
            url=url,
            separate_tickets=bool(q_dict.get("separate_tickets", 0)),
            flight_matched=q_dict.get("status") != "flight_mismatch",
            flight_mismatch_reason=q_dict.get("unverified_reason") if q_dict.get("status") == "flight_mismatch" else None,
            pax_mismatch_reason=q_dict.get("unverified_reason") if q_dict.get("status") == "passenger_mismatch" else None,
            travelers=travelers,
            provider_adults=adults,
            provider_children=children,
            has_infant=has_infant,
            checked_at=obs_at,
        )
        q_fresh = _is_quote_fresh(obs_at)
        booking_options.append({
            **q_dict,
            "api_source": q_dict.get("api_source") or "ignav",
            "url": url,
            "status": st,
            "status_label": st_label,
            "passenger_fares": _load_json(q_dict.get("passenger_fares_json"), None),
            "separate_tickets": int(q_dict.get("separate_tickets") or 0),
            "verified_party_total": verified and q_fresh,
            "unverified_reason": reason,
            "is_fresh": q_fresh,
        })

    stored_sources = _load_json(run_row["api_sources_json"], {}) if run_row else {}
    serp_quotes = [q for q in booking_options if q.get("api_source") == "serpapi"]
    ignav_quotes = [q for q in booking_options if q.get("api_source") != "serpapi"]

    serp_meta = stored_sources.get("serpapi") or {}
    ignav_meta = stored_sources.get("ignav") or {}
    serp_summary = _summarize_api_source(
        "serpapi",
        "SerpApi (Google Flights)",
        serp_meta.get("checked_at") or checked_at or "",
        serp_quotes,
        fallback_status="stale_quote" if (serp_meta.get("checked_at") and not _is_quote_fresh(serp_meta.get("checked_at"))) else (serp_meta.get("status") or "unavailable"),
        fallback_status_label=f"已逾 {price_freshness_hours()} 小時新鮮期" if (serp_meta.get("checked_at") and not _is_quote_fresh(serp_meta.get("checked_at"))) else (serp_meta.get("status_label") or "尚未查詢"),
        fallback_reason=serp_meta.get("unverified_reason"),
        fallback_url=serp_meta.get("url"),
        fallback_amount=serp_meta.get("amount"),
        fallback_scope=serp_meta.get("price_scope") or "unknown",
    )
    ignav_summary = _summarize_api_source(
        "ignav",
        "Ignav",
        ignav_meta.get("checked_at") or checked_at or "",
        ignav_quotes,
        fallback_status="stale_quote" if (ignav_meta.get("checked_at") and not _is_quote_fresh(ignav_meta.get("checked_at"))) else (ignav_meta.get("status") or "unavailable"),
        fallback_status_label=f"已逾 {price_freshness_hours()} 小時新鮮期" if (ignav_meta.get("checked_at") and not _is_quote_fresh(ignav_meta.get("checked_at"))) else (ignav_meta.get("status_label") or "尚未查詢"),
        fallback_reason=ignav_meta.get("unverified_reason"),
        fallback_url=ignav_meta.get("url"),
        fallback_amount=ignav_meta.get("amount"),
        fallback_scope=ignav_meta.get("price_scope") or "unknown",
    )
    api_sources = {
        "serpapi": {k: v for k, v in serp_summary.items() if k != "quotes"},
        "ignav": {k: v for k, v in ignav_summary.items() if k != "quotes"},
    }
    status, message = _derive_overall_p3_status(serp_summary, ignav_summary, booking_options, has_infant)
    can_decide = run_is_fresh and any(opt.get("verified_party_total") and opt.get("is_fresh") for opt in booking_options)
    return {
        "candidate_id": candidate_id,
        "itinerary": item,
        "travelers": travelers,
        "provider_travelers": {"adults": adults, "children": children, "total": adults + children},
        "checked_at": checked_at,
        "freshness_hours": price_freshness_hours(),
        "is_fresh": run_is_fresh,
        "api_sources": api_sources,
        "booking_options": booking_options,
        "channel_comparison": _channel_comparison(item),
        "can_decide": can_decide,
        "decision_persisted": False,
        "status": status,
        "message": message,
    }


def decide_candidate(
    candidate_id: str,
    *,
    persist_decision: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    with _connection() as conn:
        candidate = conn.execute("SELECT * FROM planner_candidates WHERE id=?", (candidate_id,)).fetchone()
        if not candidate:
            raise PlannerError("找不到要決選的航班候選。")
        draft = conn.execute("SELECT * FROM planner_drafts WHERE id=?", (candidate["draft_id"],)).fetchone()

    item = _normalize_stored_itinerary(_load_json(candidate["payload_json"], {}))
    traveler_data = _load_json(draft["payload_json"], {})
    travelers = traveler_data.get("travelers") or {"adults": 1, "children": []}
    adults, children, has_infant = _traveler_counts(travelers)

    if has_infant:
        return _execute_p3_dual_lookup(candidate_id, item, travelers, adults, children, has_infant)

    result: dict[str, Any] | None = None
    if persist_decision and not force_refresh:
        stored = _load_stored_p3_quotes(candidate_id, item, travelers, adults, children, has_infant)
        if stored and stored.get("is_fresh") and stored.get("can_decide"):
            result = stored

    if result is None:
        result = _execute_p3_dual_lookup(candidate_id, item, travelers, adults, children, has_infant)

    if persist_decision and result.get("can_decide"):
        with _connection() as conn:
            conn.execute(
                "INSERT INTO planner_decisions(id,candidate_id,traveler_json,confirmed_at) VALUES(1,?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(id) DO UPDATE SET candidate_id=excluded.candidate_id, traveler_json=excluded.traveler_json, confirmed_at=CURRENT_TIMESTAMP",
                (candidate_id, draft["payload_json"]),
            )
            dec_row = conn.execute("SELECT confirmed_at FROM planner_decisions WHERE id=1").fetchone()
        result["decision_persisted"] = True
        result["confirmed_at"] = dec_row["confirmed_at"] if dec_row else datetime.now(timezone.utc).isoformat()
    return result


def preview_booking_candidate(candidate_id: str) -> dict[str, Any]:
    """Fetch live SerpApi + Ignav booking quotes bypassing cache without confirming the itinerary."""
    return decide_candidate(candidate_id, persist_decision=False, force_refresh=True)


def current_decision() -> dict[str, Any] | None:
    with _connection() as conn:
        row = conn.execute(
            "SELECT d.*, c.payload_json FROM planner_decisions d "
            "JOIN planner_candidates c ON c.id=d.candidate_id WHERE d.id=1",
        ).fetchone()
    if not row:
        return None
    draft = _load_json(row["traveler_json"], {})
    travelers = draft.get("travelers") or {"adults": 1, "children": []}
    adults, children, has_infant = _traveler_counts(travelers)
    item = _normalize_stored_itinerary(_load_json(row["payload_json"], {}))
    stored = _load_stored_p3_quotes(row["candidate_id"], item, travelers, adults, children, has_infant)
    if stored:
        return {
            **stored,
            "confirmed_at": row["confirmed_at"],
            "decision_persisted": True,
        }
    status = "lookup_available" if item.get("ignav_id") else "lookup_required"
    return {
        "candidate_id": row["candidate_id"],
        "itinerary": item,
        "travelers": travelers,
        "provider_travelers": {"adults": adults, "children": children, "total": adults + children},
        "confirmed_at": row["confirmed_at"],
        "checked_at": None,
        "freshness_hours": price_freshness_hours(),
        "is_fresh": False,
        "api_sources": {
            "serpapi": _summarize_api_source("serpapi", "SerpApi (Google Flights)", "", []),
            "ignav": _summarize_api_source("ignav", "Ignav", "", []),
        },
        "booking_options": [],
        "can_decide": False,
        "decision_persisted": True,
        "status": status,
        "message": (
            "此航班尚無即時查價紀錄；按下查詢後會同時向 SerpApi 與 Ignav 即時比對去回航班並取得通路報價。"
            if status == "lookup_required" else
            "尚未取得通路報價；請點擊查詢通路以執行 SerpApi 與 Ignav 即時查價。"
        ),
        "channel_comparison": _channel_comparison(item),
    }
