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
OUTBOUND_DATE = "2027-07-11"
INBOUND_DATE = "2027-07-18"
ORIGIN = "TPE"
DESTINATION = "NGO"
FULL_SERVICE_ALLOWLIST = {"CI", "CX", "JX", "BR", "NH", "JL"}
MAX_OUTBOUND_LOOKUPS = 4

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

def request_json(params):
    url = API_BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Travel_Master flight monitor"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.load(resp)
    if data.get("error"):
        raise RuntimeError("SerpApi error: " + str(data["error"]))
    return data

def airline_code(flight_number):
    if not flight_number:
        return None
    return flight_number.replace(" ", "")[:2]

def hhmm(value):
    return value[-5:] if isinstance(value, str) and len(value) >= 5 else None

def baggage_status(item):
    text = " ".join(item.get("extensions") or []).lower()
    if "checked baggage" in text:
        return "fee" if "for a fee" in text else "mentioned_unverified"
    return "unknown"

def result_groups(data):
    return (data.get("best_flights") or []) + (data.get("other_flights") or [])

def migrate_history_if_needed():
    if not HISTORY.exists() or HISTORY.stat().st_size == 0:
        return
    with HISTORY.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        old_header = reader.fieldnames or []
        if old_header == HISTORY_HEADER:
            return
        old_rows = list(reader)

    migrated = []
    for old in old_rows:
        displayed = old.get("displayed_price_twd") or old.get("search_total_twd") or old.get("price_twd") or ""
        family = old.get("family_total_twd") or ""
        migrated.append({
            "checked_at": old.get("checked_at", ""),
            "status": old.get("status", ""),
            "source": old.get("source", ""),
            "airline": old.get("airline", ""),
            "airline_iata": old.get("airline_iata", ""),
            "outbound_flight": old.get("outbound_flight", ""),
            "outbound_departure": old.get("outbound_departure", ""),
            "outbound_arrival": old.get("outbound_arrival", ""),
            "inbound_flight": old.get("inbound_flight", ""),
            "inbound_departure": old.get("inbound_departure", ""),
            "inbound_arrival": old.get("inbound_arrival", ""),
            "displayed_price_twd": displayed,
            "price_scope": old.get("price_scope") or ("family_total" if family else "unknown"),
            "family_total_twd": family,
            "currency": old.get("currency") or "TWD",
            "baggage_status": old.get("baggage_status") or ("verified" if old.get("baggage_verified") == "True" else "unknown"),
            "time_preference_match": old.get("time_preference_match", ""),
            "notes": ("migrated_history; " + (old.get("notes") or "")).strip(),
        })

    with HISTORY.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_HEADER)
        w.writeheader()
        w.writerows(migrated)

def main():
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        print("SERPAPI_KEY is not configured; no data changed.", file=sys.stderr)
        return 2

    base = {
        "engine": "google_flights",
        "departure_id": ORIGIN,
        "arrival_id": DESTINATION,
        "outbound_date": OUTBOUND_DATE,
        "return_date": INBOUND_DATE,
        "type": 1,
        "travel_class": 1,
        "adults": 2,
        "children": 2,
        "stops": 1,
        "currency": "TWD",
        "gl": "tw",
        "hl": "zh-tw",
        "sort_by": 2,
        "api_key": api_key,
    }

    try:
        first = request_json(base)
        outbound_options = result_groups(first)
        rows = []
        lookups = 0

        for item in outbound_options:
            if lookups >= MAX_OUTBOUND_LOOKUPS:
                break
            flights = item.get("flights") or []
            if len(flights) != 1:
                continue
            out_seg = flights[0]
            code = airline_code(out_seg.get("flight_number"))
            if code not in FULL_SERVICE_ALLOWLIST:
                continue
            token = item.get("departure_token")
            if not token:
                continue

            second_params = dict(base)
            second_params["departure_token"] = token
            second = request_json(second_params)
            lookups += 1

            for ret in result_groups(second):
                rflights = ret.get("flights") or []
                if len(rflights) != 1:
                    continue
                in_seg = rflights[0]
                if airline_code(in_seg.get("flight_number")) != code:
                    continue

                out_dep = (out_seg.get("departure_airport") or {}).get("time")
                out_arr = (out_seg.get("arrival_airport") or {}).get("time")
                in_dep = (in_seg.get("departure_airport") or {}).get("time")
                in_arr = (in_seg.get("arrival_airport") or {}).get("time")
                out_t = hhmm(out_dep)
                in_arr_t = hhmm(in_arr)
                preference = bool(out_t and in_arr_t and out_t < "12:00" and in_arr_t < "21:00")

                displayed_price = ret.get("price", item.get("price"))
                rows.append({
                    "airline": out_seg.get("airline"),
                    "airline_iata": code,
                    "outbound_flight": out_seg.get("flight_number"),
                    "outbound_departure": out_dep,
                    "outbound_arrival": out_arr,
                    "inbound_flight": in_seg.get("flight_number"),
                    "inbound_departure": in_dep,
                    "inbound_arrival": in_arr,
                    "displayed_price_twd": displayed_price,
                    "price_scope": "unknown",
                    "family_total_twd": None,
                    "currency": "TWD",
                    "baggage_status": baggage_status(ret),
                    "time_preference_match": preference,
                    "source": "SerpApi Google Flights",
                })
                break

    except Exception as exc:
        # API/network/parser failure must not replace the last valid monitoring snapshot.
        print(f"SerpApi flight search failed; existing data preserved: {exc}", file=sys.stderr)
        return 2

    uniq = {}
    for row in rows:
        key = (row["outbound_flight"], row["inbound_flight"])
        old = uniq.get(key)
        p = row["displayed_price_twd"]
        old_p = old["displayed_price_twd"] if old else None
        if old is None or (isinstance(p, (int, float)) and (not isinstance(old_p, (int, float)) or p < old_p)):
            uniq[key] = row
    rows = list(uniq.values())
    rows.sort(key=lambda r: (
        0 if r["time_preference_match"] else 1,
        r["displayed_price_twd"] if isinstance(r["displayed_price_twd"], (int, float)) else float("inf"),
    ))

    checked_at = iso_now()
    status = "ok" if rows else "no_matching_offers"
    latest = {
        "schema_version": 4,
        "route": {
            "origin": ORIGIN, "destination": DESTINATION,
            "outbound_date": OUTBOUND_DATE, "inbound_date": INBOUND_DATE,
            "market": "TW", "locale": "zh-TW", "currency": "TWD",
            "cabin_class": "economy", "passengers": {"adults": 2, "children": 2},
            "nonstop_only": True,
        },
        "checked_at": checked_at,
        "status": status,
        "source": "SerpApi Google Flights",
        "source_validation": "single_source_unverified",
        "api_searches_used": 1 + lookups,
        "options": rows[:20],
        "notes": (
            "Exact-date Google Flights results via SerpApi. displayed_price_twd is stored exactly as returned, "
            "but price_scope remains unknown and family_total_twd stays null unless independently verified. "
            "Do not multiply the displayed fare by four. Checked baggage inclusion is not assumed."
        ),
    }

    LATEST.parent.mkdir(parents=True, exist_ok=True)
    migrate_history_if_needed()
    LATEST.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    exists = HISTORY.exists() and HISTORY.stat().st_size > 0
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_HEADER)
        if not exists:
            w.writeheader()
        if rows:
            for r in rows:
                w.writerow({
                    "checked_at": checked_at, "status": status, "source": "SerpApi Google Flights",
                    "airline": r["airline"], "airline_iata": r["airline_iata"],
                    "outbound_flight": r["outbound_flight"], "outbound_departure": r["outbound_departure"],
                    "outbound_arrival": r["outbound_arrival"], "inbound_flight": r["inbound_flight"],
                    "inbound_departure": r["inbound_departure"], "inbound_arrival": r["inbound_arrival"],
                    "displayed_price_twd": r["displayed_price_twd"], "price_scope": "unknown",
                    "family_total_twd": "", "currency": "TWD", "baggage_status": r["baggage_status"],
                    "time_preference_match": r["time_preference_match"], "notes": "single_source_unverified",
                })
        else:
            w.writerow({
                "checked_at": checked_at, "status": status, "source": "SerpApi Google Flights",
                "airline": "", "airline_iata": "", "outbound_flight": "", "outbound_departure": "",
                "outbound_arrival": "", "inbound_flight": "", "inbound_departure": "", "inbound_arrival": "",
                "displayed_price_twd": "", "price_scope": "unknown", "family_total_twd": "", "currency": "TWD",
                "baggage_status": "unknown", "time_preference_match": False,
                "notes": "No matching direct full-service round-trip pairs returned",
            })

    print(f"Wrote {len(rows)} matching flight pairs; SerpApi searches used: {1 + lookups}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
