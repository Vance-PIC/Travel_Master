#!/usr/bin/env python3
"""Travel_Master Flight MCP Server.

Tools:
- flight_search: ad-hoc flight search supporting dual engines (SerpApi & Ignav).
- flight_booking_links: retrieve direct booking URLs from Ignav.
- flight_monitor: operate the existing production monitor (run/status).
- flight_report: read current report data/history without API usage.

The MCP layer is intentionally an adapter. Monitoring policy remains in
skills/flight-monitor and scripts/nagoya_flight_monitor.py.
"""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

import github_store
import ignav_client

ROOT = Path(__file__).resolve().parents[1]
SERPAPI_SEARCH = "https://serpapi.com/search.json"
NAGOYA_DIR = ROOT / "travel" / "nagoya"
NAGOYA_FLIGHTS = NAGOYA_DIR / "flights"
NAGOYA_CONFIG = NAGOYA_DIR / "flight-monitor.json"
MONITOR_SCRIPT = ROOT / "scripts" / "nagoya_flight_monitor.py"

mcp = FastMCP("Travel_Master Flight MCP")


def _json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _remote_mode() -> bool:
    return os.environ.get("FLIGHT_MCP_REMOTE") == "1"


def _monitor_json(path: Path) -> dict[str, Any]:
    if not _remote_mode():
        return _json(path)
    relative = path.relative_to(ROOT).as_posix()
    try:
        value = json.loads(github_store.get_file(relative).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise github_store.GitHubStoreError("GitHub monitor JSON is invalid") from None


def _monitor_history() -> list[dict[str, str]]:
    path = NAGOYA_FLIGHTS / "itinerary_history.csv"
    if not _remote_mode():
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))
    try:
        content = github_store.get_file(path.relative_to(ROOT).as_posix()).decode("utf-8")
        reader = csv.DictReader(io.StringIO(content, newline=""))
        if not reader.fieldnames or "itinerary_key" not in reader.fieldnames:
            raise ValueError("Missing itinerary key column")
        rows = list(reader)
        if any(None in row for row in rows):
            raise ValueError("Malformed CSV row")
        return rows
    except (UnicodeDecodeError, csv.Error, ValueError):
        raise github_store.GitHubStoreError("GitHub monitor CSV is invalid") from None


def _serpapi(params: dict[str, Any]) -> dict[str, Any]:
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        raise RuntimeError("SERPAPI_KEY is not configured")
    params = {**params, "api_key": key}
    url = SERPAPI_SEARCH + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Travel_Master Flight MCP"})
        with urllib.request.urlopen(req, timeout=45) as response:
            data = json.load(response)
    except Exception:
        # urllib exceptions can include the full URL and its api_key.
        raise RuntimeError("SerpApi search request failed") from None
    if not isinstance(data, dict) or data.get("error"):
        raise RuntimeError("SerpApi search failed")
    return data


def _flight_rows(data: dict[str, Any], allowed_airlines: list[str] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    allowed = {x.upper() for x in allowed_airlines or []}
    for group_name in ("best_flights", "other_flights"):
        for item in data.get(group_name, []) or []:
            flights = item.get("flights") or []
            codes = []
            for seg in flights:
                number = str(seg.get("flight_number") or "").replace(" ", "").upper()
                if number:
                    codes.append(number[:2])
            if allowed and (not codes or any(code not in allowed for code in codes)):
                continue
            rows.append({
                "price": item.get("price"),
                "currency": data.get("search_parameters", {}).get("currency"),
                "flights": [{
                    "airline": seg.get("airline"),
                    "flight_number": seg.get("flight_number"),
                    "departure": seg.get("departure_airport"),
                    "arrival": seg.get("arrival_airport"),
                    "travel_class": seg.get("travel_class"),
                } for seg in flights],
                "stops": max(0, len(flights) - 1),
            })
    rows.sort(key=lambda r: (r["price"] is None, r["price"] or 0))
    return rows


@mcp.tool()
def flight_search(
    origin: str,
    destination: str,
    outbound_date: str,
    inbound_date: str,
    adults: int = 1,
    children: int = 0,
    infants_in_seat: int = 0,
    currency: str = "TWD",
    market: str = "TW",
    locale: str = "zh-TW",
    nonstop_only: bool = True,
    cabin_class: Literal["economy", "premium_economy", "business", "first"] = "economy",
    airlines: list[str] | None = None,
    max_results: int = 10,
    engine: Literal["auto", "serpapi", "ignav", "both"] = "auto",
) -> dict[str, Any]:
    """Ad-hoc round-trip search supporting auto (Ignav-first smart hybrid), SerpApi, and Ignav.

    In 'auto' mode, Ignav is queried first to preserve SerpApi quota. If flag carriers
    (such as China Airlines or EVA Air) are missing or specific requested airlines
    are not found, SerpApi is automatically queried to enrich and complete the results.
    """
    res: dict[str, Any] = {
        "engine": engine,
        "query": {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "outbound_date": outbound_date,
            "inbound_date": inbound_date,
            "adults": adults,
            "children": children,
            "currency": currency.upper(),
            "cabin_class": cabin_class,
        },
        "price_scope": "unknown",
        "persistence": "none",
    }

    if engine in ("serpapi", "both"):
        travel_class = {"economy": 1, "premium_economy": 2, "business": 3, "first": 4}[cabin_class]
        params: dict[str, Any] = {
            "engine": "google_flights",
            "departure_id": origin.upper(),
            "arrival_id": destination.upper(),
            "outbound_date": outbound_date,
            "return_date": inbound_date,
            "type": 1,
            "travel_class": travel_class,
            "adults": adults,
            "children": children,
            "infants_in_seat": infants_in_seat,
            "currency": currency.upper(),
            "gl": market.lower(),
            "hl": locale,
        }
        if nonstop_only:
            params["stops"] = 1
        data = _serpapi(params)
        rows = _flight_rows(data, airlines)
        res["serpapi_results"] = rows[:max(1, min(max_results, 25))]
        if engine == "serpapi":
            res["results"] = res["serpapi_results"]
            res["warning"] = "Raw API displayed prices only; do not multiply by passenger count."
            return res

    if engine in ("ignav", "both"):
        client = ignav_client.IgnavClient()
        ignav_data = client.search_round_trip(
            origin=origin,
            destination=destination,
            departure_date=outbound_date,
            return_date=inbound_date,
            adults=adults,
            children=children,
            currency=currency,
            cabin_class=cabin_class,
        )
        res["ignav_results"] = ignav_data
        if engine == "ignav":
            res["results"] = ignav_data
            return res

    if engine == "auto":
        # Step 1: Probe with Ignav first (sentinel to save SerpApi quota)
        client = ignav_client.IgnavClient()
        ignav_data = client.search_round_trip(
            origin=origin,
            destination=destination,
            departure_date=outbound_date,
            return_date=inbound_date,
            adults=adults,
            children=children,
            currency=currency,
            cabin_class=cabin_class,
        )
        res["ignav_results"] = ignav_data
        itins = ignav_data.get("itineraries", [])

        carriers = set()
        for it in itins:
            c = (it.get("outbound") or {}).get("carrier")
            if c:
                carriers.add(c.lower())

        # Check if SerpApi enrichment is needed (e.g. missing traditional flag carriers CI/BR or requested airlines)
        needs_enrichment = False
        if airlines:
            needs_enrichment = any(a.lower() not in " ".join(carriers) for a in airlines)
        elif not any("china airlines" in c or "eva" in c or "cathay" in c for c in carriers):
            needs_enrichment = True

        if needs_enrichment:
            try:
                travel_class = {"economy": 1, "premium_economy": 2, "business": 3, "first": 4}[cabin_class]
                params = {
                    "engine": "google_flights",
                    "departure_id": origin.upper(),
                    "arrival_id": destination.upper(),
                    "outbound_date": outbound_date,
                    "return_date": inbound_date,
                    "type": 1,
                    "travel_class": travel_class,
                    "adults": adults,
                    "children": children,
                    "infants_in_seat": infants_in_seat,
                    "currency": currency.upper(),
                    "gl": market.lower(),
                    "hl": locale,
                }
                if nonstop_only:
                    params["stops"] = 1
                data = _serpapi(params)
                rows = _flight_rows(data, airlines)
                res["serpapi_results"] = rows[:max(1, min(max_results, 25))]
            except Exception as e:
                res["serpapi_fallback_error"] = str(e)

        # Merge and normalize results
        merged: list[dict[str, Any]] = []
        if "serpapi_results" in res:
            for row in res["serpapi_results"]:
                item = dict(row)
                item["source"] = "serpapi"
                merged.append(item)

        for it in itins:
            out_segs = (it.get("outbound") or {}).get("segments") or []
            in_segs = (it.get("inbound") or {}).get("segments") or []
            p = it.get("price") or {}
            usd_amt = p.get("amount")
            twd_est = int(usd_amt * 31.75) if (usd_amt and currency.upper() == "TWD") else None
            ignav_row = {
                "source": "ignav",
                "airline": (it.get("outbound") or {}).get("carrier"),
                "price": twd_est if twd_est is not None else usd_amt,
                "currency": currency.upper() if twd_est is not None else p.get("currency"),
                "raw_price": p,
                "bags": it.get("bags"),
                "requires_self_transfer": it.get("requires_self_transfer"),
                "ignav_id": it.get("ignav_id"),
                "stops": max(0, len(out_segs) - 1),
                "flights": [{
                    "airline": s.get("operating_carrier_name") or s.get("marketing_carrier_code"),
                    "flight_number": f"{s.get('marketing_carrier_code', '')}{s.get('flight_number', '')}",
                    "departure": s.get("departure_airport"),
                    "arrival": s.get("arrival_airport"),
                    "departure_time": s.get("departure_time_local"),
                    "arrival_time": s.get("arrival_time_local"),
                    "aircraft": s.get("aircraft"),
                } for s in out_segs],
            }
            if nonstop_only and (len(out_segs) > 1 or len(in_segs) > 1):
                continue
            merged.append(ignav_row)

        merged.sort(key=lambda r: (r.get("price") is None, r.get("price") or 0))
        res["results"] = merged[:max(1, min(max_results, 25))]
        return res

    return res


@mcp.tool()
def flight_booking_links(
    ignav_id: str,
) -> dict[str, Any]:
    """Retrieve direct booking links for an ignav flight offer.

    Consumes Ignav quota. Returns direct links to airlines and OTAs (e.g. Trip.com).
    """
    client = ignav_client.IgnavClient()
    return client.get_booking_links(ignav_id)


@mcp.tool()
def flight_monitor(
    action: Literal["run", "status"],
    trip_id: str = "nagoya",
    mode: Literal["monitor_query", "full_query"] = "monitor_query",
    purchase_itinerary: str | None = None,
) -> dict[str, Any]:
    """Run or inspect a managed flight monitor.

    MVP managed execution currently supports trip_id='nagoya'. 'run' consumes
    SerpApi quota; 'status' is read-only.
    """
    if trip_id != "nagoya":
        return {
            "status": "unsupported_trip",
            "trip_id": trip_id,
            "message": "MVP managed monitoring currently supports nagoya only; use flight_search for ad-hoc routes.",
        }
    if action == "status":
        return {
            "trip_id": trip_id,
            "config": _monitor_json(NAGOYA_CONFIG),
            "last_run": _monitor_json(NAGOYA_FLIGHTS / "last-run.json"),
            "latest_checked_at": _monitor_json(NAGOYA_FLIGHTS / "latest.json").get("checked_at"),
        }
    if _remote_mode():
        return {"trip_id": trip_id, **github_store.dispatch_monitor(mode, purchase_itinerary)}
    cmd = [sys.executable, str(MONITOR_SCRIPT), "--mode", mode]
    if purchase_itinerary:
        cmd += ["--purchase-itinerary", purchase_itinerary]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
    return {
        "trip_id": trip_id,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
        "last_run": _json(NAGOYA_FLIGHTS / "last-run.json"),
    }


@mcp.tool()
def flight_report(
    action: Literal["current", "history"] = "current",
    trip_id: str = "nagoya",
    limit: int = 50,
) -> dict[str, Any]:
    """Read current monitor data or itinerary history. Never consumes API quota."""
    if trip_id != "nagoya":
        return {"status": "unsupported_trip", "trip_id": trip_id}
    if action == "current":
        latest = _monitor_json(NAGOYA_FLIGHTS / "latest.json")
        candidates = latest.get("itineraries", [])
        if _remote_mode() and (not isinstance(candidates, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("displayed_price_twd"), (int, float, type(None)))
            for item in candidates
        )):
            raise github_store.GitHubStoreError("GitHub monitor itinerary data is invalid")
        itineraries = sorted(
            [x for x in candidates if isinstance(x.get("displayed_price_twd"), (int, float))],
            key=lambda x: (x["displayed_price_twd"], x.get("itinerary_key", "")),
        )
        return {
            "trip_id": trip_id,
            "checked_at": latest.get("checked_at"),
            "status": latest.get("status"),
            "route": latest.get("route"),
            "top_itineraries": itineraries[:5],
            "market_candidates": latest.get("market_candidates", []),
            "execution": {k: latest.get(k) for k in (
                "mode", "searches_used", "quota_after", "monitoring_mode",
                "refreshed_outbounds", "deferred_outbounds", "baseline_complete"
            )},
        }
    rows = _monitor_history()
    return {"trip_id": trip_id, "history": rows[-max(1, min(limit, 500)):]}


if __name__ == "__main__":
    mcp.run(transport="stdio")
