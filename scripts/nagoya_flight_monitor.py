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

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "travel/nagoya/flights/latest.json"
HISTORY = ROOT / "travel/nagoya/flights/history.csv"

def iso_now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def request_json(params):
    url = API_BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Travel_Master flight monitor"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.load(resp)

def airline_code_from_flight_number(flight_number):
    if not flight_number:
        return None
    return flight_number.replace(" ", "")[:2]

def parse_time(s):
    # SerpApi Google Flights returns YYYY-MM-DD HH:MM
    return s[-5:] if isinstance(s, str) and len(s) >= 5 else None

def baggage_status(item):
    text = " ".join(item.get("extensions") or [])
    if "Checked baggage" in text:
        if "for a fee" in text:
            return "fee"
        return "mentioned"
    return "unknown"

def collect_initial_results(data):
    return (data.get("best_flights") or []) + (data.get("other_flights") or [])

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

    first = request_json(base)
    outbound_options = collect_initial_results(first)

    checked_at = iso_now()
    rows = []
    # Limit secondary requests to reduce API usage; one return lookup per useful outbound option.
    for item in outbound_options[:8]:
        flights = item.get("flights") or []
        if len(flights) != 1:
            continue
        out_seg = flights[0]
        code = airline_code_from_flight_number(out_seg.get("flight_number"))
        if code not in FULL_SERVICE_ALLOWLIST:
            continue
        token = item.get("departure_token")
        if not token:
            continue

        second_params = dict(base)
        second_params["departure_token"] = token
        # SerpApi docs: return leg requires a follow-up request with departure_token.
        second = request_json(second_params)
        return_options = collect_initial_results(second)
        if not return_options:
            continue

        for ret in return_options[:8]:
            rflights = ret.get("flights") or []
            if len(rflights) != 1:
                continue
            in_seg = rflights[0]
            in_code = airline_code_from_flight_number(in_seg.get("flight_number"))
            if in_code != code:
                continue

            out_dep = (out_seg.get("departure_airport") or {}).get("time")
            out_arr = (out_seg.get("arrival_airport") or {}).get("time")
            in_dep = (in_seg.get("departure_airport") or {}).get("time")
            in_arr = (in_seg.get("arrival_airport") or {}).get("time")
            out_t = parse_time(out_dep)
            in_arr_t = parse_time(in_arr)
            preference = bool(out_t and in_arr_t and out_t < "12:00" and in_arr_t < "21:00")

            # Google Flights/SerpApi price is retained as returned by the selected
            # 2-adult + 2-child search. We label it search_total and do not assume
            # checked baggage is included.
            price = ret.get("price", item.get("price"))
            rows.append({
                "airline": out_seg.get("airline"),
                "airline_iata": code,
                "outbound_flight": out_seg.get("flight_number"),
                "outbound_departure": out_dep,
                "outbound_arrival": out_arr,
                "inbound_flight": in_seg.get("flight_number"),
                "inbound_departure": in_dep,
                "inbound_arrival": in_arr,
                "search_total_twd": price,
                "currency": "TWD",
                "baggage_status": baggage_status(ret),
                "time_preference_match": preference,
                "source": "SerpApi Google Flights",
            })
            break

    # de-duplicate by exact flight pair
    uniq = {}
    for r in rows:
        key = (r["outbound_flight"], r["inbound_flight"])
        if key not in uniq or (r["search_total_twd"] or 10**12) < (uniq[key]["search_total_twd"] or 10**12):
            uniq[key] = r
    rows = list(uniq.values())
    rows.sort(key=lambda r: (
        0 if r["time_preference_match"] else 1,
        r["search_total_twd"] if isinstance(r["search_total_twd"], (int, float)) else float("inf"),
    ))

    status = "ok" if rows else "no_matching_offers"
    latest = {
        "schema_version": 2,
        "route": {
            "origin": ORIGIN,
            "destination": DESTINATION,
            "outbound_date": OUTBOUND_DATE,
            "inbound_date": INBOUND_DATE,
            "market": "TW",
            "locale": "zh-TW",
            "currency": "TWD",
            "cabin_class": "economy",
            "passengers": {"adults": 2, "children": 2},
            "nonstop_only": True,
        },
        "checked_at": checked_at,
        "status": status,
        "source": "SerpApi Google Flights",
        "source_validation": "single_source_unverified",
        "options": rows[:20],
        "notes": (
            "Exact-date Google Flights search via SerpApi. Return leg resolved using departure_token. "
            "Price is recorded exactly as returned for the configured 2-adult/2-child search. "
            "Checked baggage inclusion is not assumed; baggage_status must be reviewed. "
            "A second independent source is still required before treating a fare as fully verified."
        ),
    }
    LATEST.parent.mkdir(parents=True, exist_ok=True)
    LATEST.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    header = [
        "checked_at","status","source","airline","airline_iata",
        "outbound_flight","outbound_departure","outbound_arrival",
        "inbound_flight","inbound_departure","inbound_arrival",
        "search_total_twd","currency","baggage_status","time_preference_match","notes"
    ]
    exists = HISTORY.exists()
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if not exists or HISTORY.stat().st_size == 0:
            w.writeheader()
        if rows:
            for r in rows:
                w.writerow({
                    "checked_at": checked_at,
                    "status": status,
                    "source": "SerpApi Google Flights",
                    "airline": r["airline"],
                    "airline_iata": r["airline_iata"],
                    "outbound_flight": r["outbound_flight"],
                    "outbound_departure": r["outbound_departure"],
                    "outbound_arrival": r["outbound_arrival"],
                    "inbound_flight": r["inbound_flight"],
                    "inbound_departure": r["inbound_departure"],
                    "inbound_arrival": r["inbound_arrival"],
                    "search_total_twd": r["search_total_twd"],
                    "currency": r["currency"],
                    "baggage_status": r["baggage_status"],
                    "time_preference_match": r["time_preference_match"],
                    "notes": "single_source_unverified",
                })
        else:
            w.writerow({
                "checked_at": checked_at, "status": status, "source": "SerpApi Google Flights",
                "airline": "", "airline_iata": "", "outbound_flight": "",
                "outbound_departure": "", "outbound_arrival": "",
                "inbound_flight": "", "inbound_departure": "", "inbound_arrival": "",
                "search_total_twd": "", "currency": "TWD", "baggage_status": "unknown",
                "time_preference_match": False, "notes": "No matching direct full-service round-trip pairs returned",
            })

    print(f"Wrote {len(rows)} matching flight pairs to {LATEST} and {HISTORY}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
