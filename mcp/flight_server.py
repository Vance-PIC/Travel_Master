#!/usr/bin/env python3
"""Travel_Master Flight MCP MVP.

Three public tools:
- flight_search: ad-hoc SerpApi Google Flights search; no persistence.
- flight_monitor: operate the existing production monitor (run/status).
- flight_report: read current report data/history without API usage.

The MCP layer is intentionally an adapter. Monitoring policy remains in
skills/flight-monitor and scripts/nagoya_flight_monitor.py.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

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


def _serpapi(params: dict[str, Any]) -> dict[str, Any]:
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        raise RuntimeError("SERPAPI_KEY is not configured")
    params = {**params, "api_key": key}
    url = SERPAPI_SEARCH + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Travel_Master Flight MCP"})
    with urllib.request.urlopen(req, timeout=45) as response:
        data = json.load(response)
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
) -> dict[str, Any]:
    """Ad-hoc round-trip search. Does not create monitoring/history.

    This tool consumes SerpApi quota. Prices are raw API displayed prices;
    never infer per-person/family scope by multiplying them.
    """
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
    return {
        "query": {k: v for k, v in params.items() if k != "api_key"},
        "price_scope": "unknown",
        "persistence": "none",
        "results": rows[:max(1, min(max_results, 25))],
        "warning": "Raw API displayed prices only; do not multiply by passenger count.",
    }


@mcp.tool()
def flight_monitor(
    action: Literal["run", "status"],
    trip_id: str = "nagoya",
    mode: Literal["monitor_query", "full_query"] = "monitor_query",
    purchase_itinerary: str | None = None,
) -> dict[str, Any]:
    """Run or inspect a managed flight monitor.

    MVP managed execution currently supports trip_id='nagoya'. 'run' consumes
    SerpApi quota; 'status' is read-only. New trip creation is intentionally
    deferred until the production executor is generalized.
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
            "config": _json(NAGOYA_CONFIG),
            "last_run": _json(NAGOYA_FLIGHTS / "last-run.json"),
            "latest_checked_at": _json(NAGOYA_FLIGHTS / "latest.json").get("checked_at"),
        }
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
        latest = _json(NAGOYA_FLIGHTS / "latest.json")
        itineraries = sorted(
            [x for x in latest.get("itineraries", []) if isinstance(x.get("displayed_price_twd"), (int, float))],
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
    path = NAGOYA_FLIGHTS / "itinerary_history.csv"
    if not path.exists():
        return {"trip_id": trip_id, "history": []}
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {"trip_id": trip_id, "history": rows[-max(1, min(limit, 500)):]} 


if __name__ == "__main__":
    mcp.run(transport="stdio")
