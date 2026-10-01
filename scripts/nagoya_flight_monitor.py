#!/usr/bin/env python3
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://serpapi.com/search.json"
ACCOUNT_BASE = "https://serpapi.com/account.json"
CONFIG = Path(__file__).resolve().parents[1] / "travel/nagoya/flight-monitor.json"

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "travel/nagoya/flights/latest.json"
HISTORY = ROOT / "travel/nagoya/flights/history.csv"

HISTORY_HEADER = [
    "checked_at","status","source","airline","airline_iata",
    "outbound_flight","outbound_departure","outbound_arrival",
    "inbound_flight","inbound_departure","inbound_arrival",
    "displayed_price_twd","price_scope","family_total_twd","currency",
    "baggage_status","time_preference_match","notes"
]

def iso_now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def request_json(params, endpoint=API_BASE):
    url = endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Travel_Master flight monitor"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.load(resp)
    if not isinstance(data, dict) or data.get("error"):
        raise RuntimeError("Invalid response or SerpApi error")
    return data

def airline_code(flight_number):
    if not flight_number:
        return None
    return flight_number.replace(" ", "")[:2]

def baggage_status(item):
    text = " ".join(item.get("extensions") or []).lower()
    if "checked baggage" in text:
        return "fee" if "for a fee" in text else "mentioned_unverified"
    return "unknown"

def result_groups(data):
    if not any(k in data for k in ("best_flights", "other_flights")):
        if data.get("search_information", {}).get("flights_results_state") != "Fully empty":
            raise ValueError("Flight result groups missing")
    for key in ("best_flights", "other_flights"):
        if key in data and not isinstance(data[key], list):
            raise ValueError("Invalid flight result group")
    return (data.get("best_flights") or []) + (data.get("other_flights") or [])

def quota_state(account):
    usage = account.get("this_month_usage")
    remaining = account.get("total_searches_left")
    if type(usage) is not int or type(remaining) is not int or min(usage, remaining) < 0:
        raise ValueError("Account usage/remaining unavailable")
    tier = ("preserve" if usage >= 240 or remaining == 0 else
            "market_only" if usage >= 225 else "reduced" if usage >= 200 else "normal")
    return {"usage": usage, "remaining": remaining, "tier": tier,
            "plan_searches_left": account.get("plan_searches_left"),
            "renewal_date": account.get("plan_renewal_date")}


def preference(value, cutoff):
    if value is None:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M").strftime("%H:%M") < cutoff


def candidate(item, cfg, inbound=False):
    if not isinstance(item, dict) or not isinstance(item.get("flights"), list):
        raise ValueError("Malformed flight item")
    flights = item["flights"]
    if len(flights) != 1:
        return None
    seg = flights[0]
    code = airline_code(seg.get("flight_number"))
    dep, arr = seg.get("departure_airport", {}), seg.get("arrival_airport", {})
    origin, destination = (cfg["destination"], cfg["origin"]) if inbound else (cfg["origin"], cfg["destination"])
    date = cfg["inbound_date"] if inbound else cfg["outbound_date"]
    if code not in cfg["full_service_airlines"]:
        return None
    if dep.get("id") != origin or arr.get("id") != destination:
        return None
    if not isinstance(dep.get("time"), str) or not dep["time"].startswith(date + " "):
        raise ValueError("Unexpected departure date")
    if seg.get("travel_class") != "Economy":
        return None
    price = item.get("price")
    if type(price) not in (int, float) or price <= 0:
        raise ValueError("Invalid displayed price")
    prefix = "inbound" if inbound else "outbound"
    match = preference(arr.get("time") if inbound else dep.get("time"),
                       cfg["preferences"]["inbound_arrival_before" if inbound else "outbound_before"])
    return {"airline": seg.get("airline"), "airline_iata": code,
            prefix + "_flight": seg.get("flight_number"),
            prefix + "_departure": dep.get("time"), prefix + "_arrival": arr.get("time"),
            "displayed_price_twd": price, "price_scope": "unknown", "family_total_twd": None,
            "currency": "TWD", "baggage_status": baggage_status(item),
            prefix + "_preference_match": match, "time_preference_match": None,
            "departure_token_available": bool(item.get("departure_token"))}


def deep_reasons(row, previous, lows, cfg):
    reasons = []
    key = row["outbound_flight"]
    old = next((r for r in previous if r.get("outbound_flight") == key), None)
    if previous and not old:
        reasons.append("new_airline" if row["airline_iata"] not in {r.get("airline_iata") for r in previous} else "new_flight")
    if not previous:
        reasons.append("initial_baseline")
    price = row["displayed_price_twd"]
    low = lows.get(key)
    if type(low) in (int, float) and price < low:
        reasons.append("new_low")
    if old and type(old.get("displayed_price_twd")) in (int, float) and price <= old["displayed_price_twd"] * (1 - cfg["drop_fraction"]):
        reasons.append("drop_5_percent")
    # Only independently verified family totals may trigger a family budget comparison.
    total = row.get("family_total_twd")
    if row.get("price_scope") == "family_total" and type(total) in (int, float) and total <= cfg["family_target_twd"] * (1 + cfg["target_margin_fraction"]):
        reasons.append("near_family_target")
    return reasons


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def main():
    searches = 0
    account_calls = 0
    before = after = None
    stage = "configuration"
    attempt = {"checked_at": iso_now(), "status": "error"}
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        key = os.environ.get("SERPAPI_KEY")
        if not key:
            raise ValueError("SERPAPI_KEY is not configured")
        previous = json.loads(LATEST.read_text(encoding="utf-8")) if LATEST.exists() else {}
        previous_route = previous.get("route")
        if previous_route and any(previous_route.get(k) != cfg[k] for k in
                                  ("origin", "destination", "outbound_date", "inbound_date", "passengers")):
            previous = {}
        base = {"engine": "google_flights", "departure_id": cfg["origin"],
                "arrival_id": cfg["destination"], "outbound_date": cfg["outbound_date"],
                "return_date": cfg["inbound_date"], "type": 1, "travel_class": 1,
                "adults": cfg["passengers"]["adults"], "children": cfg["passengers"]["children"],
                "stops": 1, "currency": "TWD", "gl": "tw", "hl": "zh-tw",
                "include_airlines": ",".join(cfg["full_service_airlines"]), "api_key": key}
        stage = "account_before"
        account_calls += 1
        before = quota_state(request_json({"api_key": key}, ACCOUNT_BASE))
        if before["tier"] == "preserve":
            attempt.update(status="quota_preserved", quota_before=before, searches_used=0, account_calls=account_calls)
            atomic_json(LATEST.parent / "last-run.json", attempt)
            print(json.dumps(attempt))
            return 0
        stage = "market_scan"
        searches += 1
        first = request_json(base)
        market, tokens = [], {}
        for item in result_groups(first):
            row = candidate(item, cfg)
            if row:
                market.append(row)
                if item.get("departure_token"):
                    tokens[row["outbound_flight"]] = item["departure_token"]
        lows = dict(previous.get("market_price_lows", {}))
        for old in previous.get("market_candidates", []):
            value = old.get("displayed_price_twd")
            flight = old.get("outbound_flight")
            if type(value) in (int, float):
                lows[flight] = min(lows.get(flight, value), value)
        for row in market:
            row["deep_search_triggers"] = deep_reasons(row, previous.get("market_candidates", []), lows, cfg)
        stage = "account_after_market"
        account_calls += 1
        after = quota_state(request_json({"api_key": key}, ACCOUNT_BASE))
        # Conservative local estimate also protects against delayed account counters.
        projected = dict(after)
        projected["usage"] = max(after["usage"], before["usage"] + searches)
        projected["remaining"] = min(after["remaining"], before["remaining"] - searches)
        budget = quota_state({"this_month_usage": projected["usage"], "total_searches_left": max(0, projected["remaining"])})
        eligible = [r for r in market if r["deep_search_triggers"] and r["outbound_flight"] in tokens]
        if budget["tier"] == "reduced":
            eligible = [r for r in eligible if set(r["deep_search_triggers"]) & {"drop_5_percent", "near_family_target"}]
        rows = []
        if eligible and budget["tier"] in ("normal", "reduced"):
            chosen = min(eligible, key=lambda r: ("drop_5_percent" not in r["deep_search_triggers"], r["displayed_price_twd"]))
            stage = "deep_search"
            searches += 1
            second = request_json(dict(base, departure_token=tokens[chosen["outbound_flight"]]))
            for item in result_groups(second):
                ret = candidate(item, cfg, inbound=True)
                if ret:
                    row = dict(chosen)
                    row.update({k: v for k, v in ret.items() if k.startswith("inbound_")})
                    row["inbound_airline_iata"] = ret["airline_iata"]
                    row.update(displayed_price_twd=ret["displayed_price_twd"], baggage_status=ret["baggage_status"])
                    flags = [row["outbound_preference_match"], row["inbound_preference_match"]]
                    row["time_preference_match"] = False if False in flags else (None if None in flags else True)
                    rows.append(row)
            stage = "account_after_deep"
            account_calls += 1
            after = quota_state(request_json({"api_key": key}, ACCOUNT_BASE))
        for row in market:
            flight, value = row["outbound_flight"], row["displayed_price_twd"]
            lows[flight] = min(lows.get(flight, value), value)
        attempt.update(status="ok" if market else "no_matching_offers", searches_used=searches,
                       api_searches_used=searches, account_calls=account_calls, quota_before=before,
                       quota_after=after, actual_usage_delta=after["usage"] - before["usage"],
                       monitoring_mode="market_plus_return" if searches == 2 else "market_only")
        latest = dict(attempt, schema_version=5, route=cfg, source="SerpApi Google Flights",
                      source_validation="single_source_unverified", market_candidates=market,
                      options=rows, market_price_lows=lows,
                      notes="Prices retain unknown scope; family totals and baggage are unverified. Preferences never exclude eligible offers. Empty options may mean deep search was not performed.")
        stage = "persistence"
        # Write history first; never replace the valid snapshot on a history write failure.
        header = HISTORY_HEADER + ["record_type", "searches_used", "quota_status", "quota_usage", "quota_remaining", "outbound_preference_match", "inbound_preference_match", "inbound_airline_iata", "deep_search_triggers"]
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        if HISTORY.exists():
            with HISTORY.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                old_rows = list(reader)
                header += [name for name in (reader.fieldnames or []) if name not in header]
        else:
            old_rows = []
        temp = HISTORY.with_suffix(".csv.tmp")
        with temp.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(old_rows)
            for kind, items in (("market", market), ("round_trip", rows)):
                for row in items:
                    writer.writerow(dict(row, checked_at=attempt["checked_at"], status=attempt["status"], source="SerpApi Google Flights", record_type=kind, searches_used=searches, quota_status=after["tier"], quota_usage=after["usage"], quota_remaining=after["remaining"], deep_search_triggers=";".join(row["deep_search_triggers"])))
            if not market:
                writer.writerow(dict(checked_at=attempt["checked_at"], status=attempt["status"], record_type="run", searches_used=searches, quota_status=after["tier"], quota_usage=after["usage"], quota_remaining=after["remaining"]))
        temp.replace(HISTORY)
        atomic_json(LATEST, latest)
        atomic_json(LATEST.parent / "last-run.json", attempt)
        print(json.dumps(dict(attempt, airlines=sorted({r["airline_iata"] for r in market}))))
        return 0
    except Exception as exc:
        # Do not persist exception strings: HTTP errors can contain credential URLs.
        attempt.update(error_type=type(exc).__name__, error_stage=stage,
                       error="Monitoring failed; last valid snapshot preserved. Inspect stage and configuration.",
                       searches_used=searches, account_calls=account_calls, quota_before=before, quota_after=after)
        atomic_json(LATEST.parent / "last-run.json", attempt)
        print(json.dumps(attempt), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
