#!/usr/bin/env python3
import csv
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://api.duffel.com"
OUTBOUND_DATE = "2027-07-11"
INBOUND_DATE = "2027-07-18"
ORIGIN = "TPE"
DESTINATION = "NGO"
FULL_SERVICE_ALLOWLIST = {"CI", "CX", "JX", "BR", "NH", "JL"}

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "travel/nagoya/flights/latest.json"
HISTORY = ROOT / "travel/nagoya/flights/history.csv"

def request_json(method, path, token, body=None):
    data = None
    headers = {
        "Accept": "application/json",
        "Duffel-Version": "v2",
        "Authorization": f"Bearer {token}",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API_BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.load(resp)

def iso_now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def tpart(dt):
    return dt[11:16] if isinstance(dt, str) and len(dt) >= 16 else None

def flight_no(seg):
    carrier = (seg.get("marketing_carrier") or {}).get("iata_code") or (seg.get("operating_carrier") or {}).get("iata_code")
    num = seg.get("marketing_carrier_flight_number") or seg.get("operating_carrier_flight_number")
    return f"{carrier}{num}" if carrier and num else None

def baggage_verified(offer):
    # Duffel can expose baggage allowances at passenger/segment level. We only mark
    # verified when a checked-bag quantity/weight is explicitly present.
    for sl in offer.get("slices", []):
        for seg in sl.get("segments", []):
            for p in seg.get("passengers", []):
                for bag in p.get("baggages", []) or []:
                    if bag.get("type") == "checked" and (
                        (bag.get("quantity") or 0) > 0 or bag.get("weight") is not None
                    ):
                        return True
    return False

def main():
    token = os.environ.get("DUFFEL_ACCESS_TOKEN")
    if not token:
        print("DUFFEL_ACCESS_TOKEN is not configured; no data changed.", file=sys.stderr)
        return 2

    payload = {
        "data": {
            "slices": [
                {"origin": ORIGIN, "destination": DESTINATION, "departure_date": OUTBOUND_DATE},
                {"origin": DESTINATION, "destination": ORIGIN, "departure_date": INBOUND_DATE},
            ],
            "passengers": [
                {"type": "adult"},
                {"type": "adult"},
                {"age": 9},
                {"age": 7},
            ],
            "cabin_class": "economy",
            "max_connections": 0,
        }
    }

    created = request_json(
        "POST",
        "/air/offer_requests?return_offers=false&supplier_timeout=10000",
        token,
        payload,
    )
    offer_request_id = created["data"]["id"]
    q = urllib.parse.urlencode({
        "offer_request_id": offer_request_id,
        "sort": "total_amount",
        "max_connections": 0,
        "limit": 200,
    })
    offers_resp = request_json("GET", f"/air/offers?{q}", token)
    offers = offers_resp.get("data", [])

    checked_at = iso_now()
    rows = []
    for offer in offers:
        owner = offer.get("owner") or {}
        code = owner.get("iata_code")
        if code not in FULL_SERVICE_ALLOWLIST:
            continue

        slices = offer.get("slices") or []
        if len(slices) != 2:
            continue
        out_segments = slices[0].get("segments") or []
        in_segments = slices[1].get("segments") or []
        if len(out_segments) != 1 or len(in_segments) != 1:
            continue

        out_seg, in_seg = out_segments[0], in_segments[0]
        out_dep, out_arr = out_seg.get("departing_at"), out_seg.get("arriving_at")
        in_dep, in_arr = in_seg.get("departing_at"), in_seg.get("arriving_at")

        currency = offer.get("total_currency")
        amount = offer.get("total_amount")
        try:
            total = float(amount) if amount is not None else None
        except (TypeError, ValueError):
            total = None

        preference = bool(tpart(out_dep) and tpart(in_arr) and tpart(out_dep) < "12:00" and tpart(in_arr) < "21:00")
        rows.append({
            "airline": owner.get("name"),
            "airline_iata": code,
            "outbound_flight": flight_no(out_seg),
            "outbound_departure": out_dep,
            "outbound_arrival": out_arr,
            "inbound_flight": flight_no(in_seg),
            "inbound_departure": in_dep,
            "inbound_arrival": in_arr,
            "family_total": total,
            "currency": currency,
            "baggage_verified": baggage_verified(offer),
            "time_preference_match": preference,
            "offer_id": offer.get("id"),
            "expires_at": offer.get("expires_at"),
        })

    rows.sort(key=lambda r: (
        0 if r["time_preference_match"] else 1,
        r["family_total"] if r["family_total"] is not None else float("inf"),
    ))

    status = "ok" if rows else "no_matching_offers"
    latest = {
        "schema_version": 1,
        "route": {
            "origin": ORIGIN,
            "destination": DESTINATION,
            "outbound_date": OUTBOUND_DATE,
            "inbound_date": INBOUND_DATE,
            "market": "TW",
            "locale": "zh-TW",
            "currency": "TWD",
            "cabin_class": "economy",
            "passengers": {"adults": 2, "children_ages": [9, 7]},
        },
        "checked_at": checked_at,
        "status": status,
        "source": "Duffel",
        "source_validation": "single_source_unverified",
        "offer_request_id": offer_request_id,
        "options": rows[:20],
        "notes": "Direct full-service results only. Duffel total is the searched 2A2C offer total; currency may not be TWD. A second independent source is still required before treating a fare as fully verified.",
    }
    LATEST.parent.mkdir(parents=True, exist_ok=True)
    LATEST.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    header = [
        "checked_at","status","source","airline","airline_iata",
        "outbound_flight","outbound_departure","outbound_arrival",
        "inbound_flight","inbound_departure","inbound_arrival",
        "family_total","currency","baggage_verified","time_preference_match","notes"
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
                    "source": "Duffel",
                    "airline": r["airline"],
                    "airline_iata": r["airline_iata"],
                    "outbound_flight": r["outbound_flight"],
                    "outbound_departure": r["outbound_departure"],
                    "outbound_arrival": r["outbound_arrival"],
                    "inbound_flight": r["inbound_flight"],
                    "inbound_departure": r["inbound_departure"],
                    "inbound_arrival": r["inbound_arrival"],
                    "family_total": r["family_total"],
                    "currency": r["currency"],
                    "baggage_verified": r["baggage_verified"],
                    "time_preference_match": r["time_preference_match"],
                    "notes": "single_source_unverified",
                })
        else:
            w.writerow({
                "checked_at": checked_at, "status": status, "source": "Duffel",
                "airline": "", "airline_iata": "", "outbound_flight": "",
                "outbound_departure": "", "outbound_arrival": "",
                "inbound_flight": "", "inbound_departure": "", "inbound_arrival": "",
                "family_total": "", "currency": "", "baggage_verified": False,
                "time_preference_match": False, "notes": "No matching direct full-service offers returned",
            })

    print(f"Wrote {len(rows)} matching offers to {LATEST} and {HISTORY}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
