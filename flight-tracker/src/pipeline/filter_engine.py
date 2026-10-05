"""SPEC 2.3 航班時刻硬性過濾規則引擎。

過濾結果以 `passes_strict_rule` 旗標回傳而非直接刪除資料，
因為 GUI 需要即時開關硬性過濾（見 mockup toggleStrictRules）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.config import departure_cutoff, load_settings


def _weekday(flight_date: str) -> int:
    """回傳 0=Mon ... 5=Sat, 6=Sun"""
    return datetime.strptime(flight_date, "%Y-%m-%d").weekday()


def _to_minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def passes_strict_rule(
    flight_date: str, trip_type: str, departure_time: str,
    settings: Optional[dict] = None,
) -> bool:
    """
    去程限制（週日）：出發時間 < 15:00
    回程限制：週六 < 20:00；週日 < 14:00
    其餘情況（非週日去程 / 非週六週日回程）預設通過。
    """
    weekday = _weekday(flight_date)
    dep_minutes = _to_minutes(departure_time)
    if settings is None:
        settings = load_settings()
    rules = settings.get("strict_time_rules", {})
    configured_cutoff = departure_cutoff(flight_date, trip_type, settings)
    if configured_cutoff:
        return dep_minutes < _to_minutes(configured_cutoff)
    outbound_limit = rules.get("outbound_sunday_before", "15:00")
    inbound_sat_limit = rules.get("inbound_saturday_before", "20:00")
    inbound_sun_limit = rules.get("inbound_sunday_before", "14:00")

    if trip_type == "OUTBOUND" and weekday == 6:  # Sunday
        return dep_minutes < _to_minutes(outbound_limit)

    if trip_type == "INBOUND" and weekday == 5:  # Saturday
        return dep_minutes < _to_minutes(inbound_sat_limit)

    if trip_type == "INBOUND" and weekday == 6:  # Sunday
        return dep_minutes < _to_minutes(inbound_sun_limit)

    return True


def resolve_airline(raw_code: Optional[str], settings: Optional[dict] = None) -> dict:
    """把爬蟲/mock 給的原始 airline_code（可能是 IATA 代碼或全名）正規化為統一顯示名稱＋廉航旗標。

    airlines 對照表以代碼（如 CI）為唯一 key；爬蟲資料的 airline_code 欄位實際存的是
    航空公司全名（如「中華航空」），故代碼比對失敗時，再以 name_zh 反查比對一次。
    兩者皆未登記者，視為未知航空公司，保留原始字串顯示、預設非廉航（避免誤刪未登記的傳統航空資料）。
    """
    if not raw_code:
        return {"name_zh": raw_code, "is_lcc": False}
    if settings is None:
        settings = load_settings()
    airlines = settings.get("airlines", {})
    info = airlines.get(raw_code)
    if not info:
        info = next((v for v in airlines.values() if v["name_zh"] == raw_code), None)
    if not info:
        return {"name_zh": raw_code, "is_lcc": False}
    return {"name_zh": info["name_zh"], "is_lcc": bool(info.get("is_lcc", False))}


def annotate_flights(flights: list[dict], settings: Optional[dict] = None) -> list[dict]:
    """為每筆航班附加 passes_strict_rule／airline_name／is_lcc 欄位（不修改/移除原始資料）。"""
    annotated = []
    for flight in flights:
        result = dict(flight)
        result["passes_strict_rule"] = passes_strict_rule(
            flight["flight_date"], flight["trip_type"], flight["departure_time"], settings,
        )
        airline_info = resolve_airline(flight.get("airline_code"), settings)
        result["airline_name"] = airline_info["name_zh"]
        result["is_lcc"] = airline_info["is_lcc"]
        annotated.append(result)
    return annotated
