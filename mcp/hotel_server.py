#!/usr/bin/env python3
"""Travel_Master Hotel MCP.

Three public tools:
- hotel_search: ad-hoc Google Hotels search via SearchAPI or SerpApi (shared SERPAPI_KEY).
- hotel_monitor: operate the existing production monitor (run/status).
- hotel_report: read current report data/history without API usage.

The MCP layer is intentionally an adapter. Monitoring policy remains in
skills/hotel-monitor and scripts/hotel_executor.py.
"""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

import github_store

ROOT = Path(__file__).resolve().parents[1]
SEARCHAPI_ENDPOINT = "https://www.searchapi.io/api/v1/search"
SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
NAGOYA_HOTELS_DIR = ROOT / "travel" / "nagoya" / "hotels"
NAGOYA_HOTEL_CONFIG = ROOT / "travel" / "nagoya" / "hotel-monitor.json"
HOTEL_EXECUTOR_SCRIPT = ROOT / "scripts" / "hotel_executor.py"

mcp = FastMCP("Travel_Master Hotel MCP")


def _json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _remote_mode() -> bool:
    return any(os.environ.get(k) == "1" for k in ("HOTEL_MCP_REMOTE", "TRAVEL_MCP_REMOTE", "FLIGHT_MCP_REMOTE"))


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


def _monitor_history(monitor_id: str) -> list[dict[str, str]]:
    path = NAGOYA_HOTELS_DIR / monitor_id / "history.csv"
    if not _remote_mode():
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))
    try:
        content = github_store.get_file(path.relative_to(ROOT).as_posix()).decode("utf-8")
        reader = csv.DictReader(io.StringIO(content, newline=""))
        if not reader.fieldnames:
            return []
        rows = list(reader)
        if any(None in row for row in rows):
            raise ValueError("Malformed CSV row")
        return rows
    except (UnicodeDecodeError, csv.Error, ValueError):
        raise github_store.GitHubStoreError("GitHub monitor CSV is invalid") from None


def _fetch_hotel_data(params: dict[str, Any]) -> dict[str, Any]:
    """Fetch Google Hotels data using SearchAPI or SerpApi (shared key)."""
    searchapi_key = os.environ.get("SEARCHAPI_KEY")
    serpapi_key = os.environ.get("SERPAPI_KEY")

    if searchapi_key:
        url = SEARCHAPI_ENDPOINT + "?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Travel_Master Hotel MCP",
                    "Authorization": f"Bearer {searchapi_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=45) as response:
                data = json.load(response)
        except Exception:
            raise RuntimeError("SearchAPI search request failed") from None
        if not isinstance(data, dict) or data.get("error") or data.get("errors"):
            raise RuntimeError("SearchAPI search failed")
        return data

    if serpapi_key:
        api_params = {**params, "api_key": serpapi_key}
        url = SERPAPI_ENDPOINT + "?" + urllib.parse.urlencode(api_params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Travel_Master Hotel MCP"})
            with urllib.request.urlopen(req, timeout=45) as response:
                data = json.load(response)
        except Exception:
            raise RuntimeError("SerpApi Google Hotels request failed") from None
        if not isinstance(data, dict) or data.get("error"):
            raise RuntimeError("SerpApi Google Hotels search failed")
        return data

    raise RuntimeError("SEARCHAPI_KEY is not configured")


def _hotel_rows(
    data: dict[str, Any],
    min_price: int | None,
    max_price: int | None,
    rating_floor: float | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in data.get("properties", []) or []:
        nightly = item.get("rate_per_night") or {}
        total = item.get("total_rate") or {}
        price = None
        if isinstance(total, dict):
            price = total.get("extracted_price") or total.get("extracted_lowest")
        if price is None and isinstance(nightly, dict):
            price = nightly.get("extracted_price") or nightly.get("extracted_lowest")
        if price is None and isinstance(item.get("price"), (int, float)):
            price = item["price"]

        if min_price is not None and price is not None and price < min_price:
            continue
        if max_price is not None and price is not None and price > max_price:
            continue

        curr_rating = item.get("overall_rating") or item.get("rating")
        if rating_floor is not None and (curr_rating is None or float(curr_rating) < rating_floor):
            continue
        rows.append({
            "name": item.get("name"),
            "hotel_class": item.get("hotel_class") or item.get("extracted_hotel_class"),
            "price": price,
            "total_rate": total.get("lowest") if isinstance(total, dict) else None,
            "rate_per_night": nightly.get("lowest") if isinstance(nightly, dict) else None,
            "overall_rating": curr_rating,
            "reviews": item.get("reviews"),
            "amenities": item.get("amenities") or [],
            "deal": item.get("deal") or item.get("deal_description"),
            "data_id": item.get("data_id"),
            "gps_coordinates": item.get("gps_coordinates"),
        })
    rows.sort(key=lambda r: (r["price"] is None, r["price"] or 0))
    return rows


@mcp.tool()
def hotel_search(
    q: str,
    check_in_date: str,
    check_out_date: str,
    adults: int = 2,
    children: int = 0,
    child_ages: list[int] | None = None,
    currency: str = "TWD",
    market: str = "tw",
    locale: str = "zh-TW",
    min_price: int | None = None,
    max_price: int | None = None,
    rating: float | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """Ad-hoc Google Hotels search via SearchAPI or SerpApi (shares SERPAPI_KEY).

    This tool consumes SearchAPI or SerpApi quota. Prices are raw API displayed prices;
    never infer room qualification or tax inclusion without Stage evaluation.
    """
    params: dict[str, Any] = {
        "engine": "google_hotels",
        "q": q,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "adults": adults,
        "currency": currency.upper(),
        "gl": market.lower(),
        "hl": locale,
    }
    if children > 0:
        params["children"] = children
        if child_ages:
            params["children_ages"] = ",".join(str(a) for a in child_ages[:children])

    data = _fetch_hotel_data(params)
    rows = _hotel_rows(data, min_price, max_price, rating)
    return {
        "query": {k: v for k, v in params.items() if k != "api_key"},
        "price_scope": "unknown",
        "persistence": "none",
        "results": rows[:max(1, min(max_results, 25))],
        "warning": "Raw API displayed prices only; does not infer total taxes or guarantee policy match without stage evaluation.",
    }


@mcp.tool()
def hotel_monitor(
    action: Literal["run", "status"],
    trip_id: str = "nagoya",
    monitor_id: Literal["marunouchi-booked", "airport-candidate"] = "marunouchi-booked",
    request_json: str | None = None,
) -> dict[str, Any]:
    """Run or inspect a managed hotel monitor.

    MVP managed execution currently supports trip_id='nagoya'. 'run' consumes
    SearchAPI quota; 'status' is read-only.
    """
    if trip_id != "nagoya":
        return {
            "status": "unsupported_trip",
            "trip_id": trip_id,
            "message": "MVP managed hotel monitoring currently supports nagoya only; use hotel_search for ad-hoc queries.",
        }
    if monitor_id not in ("marunouchi-booked", "airport-candidate"):
        return {
            "status": "unsupported_monitor",
            "trip_id": trip_id,
            "monitor_id": monitor_id,
        }
    if action == "status":
        monitor_dir = NAGOYA_HOTELS_DIR / monitor_id
        config = _monitor_json(NAGOYA_HOTEL_CONFIG)
        if _remote_mode() and "monitors" in config:
            target = next((m for m in config["monitors"] if m.get("monitor_id") == monitor_id), config)
        else:
            target = config
        latest = _monitor_json(monitor_dir / "latest.json")
        return {
            "trip_id": trip_id,
            "monitor_id": monitor_id,
            "config": target,
            "last_run": _monitor_json(monitor_dir / "last-run.json"),
            "latest": latest,
            "latest_status": latest.get("status"),
        }
    if _remote_mode():
        return {"trip_id": trip_id, **github_store.dispatch_hotel_monitor(monitor_id, request_json)}

    cmd = [sys.executable, str(HOTEL_EXECUTOR_SCRIPT), "--monitor-id", monitor_id]
    tmp_path = None
    if request_json:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as f:
            f.write(request_json)
            tmp_path = f.name
        cmd += ["--request-file", tmp_path]
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
    finally:
        if tmp_path and Path(tmp_path).exists():
            Path(tmp_path).unlink()

    monitor_dir = NAGOYA_HOTELS_DIR / monitor_id
    return {
        "trip_id": trip_id,
        "monitor_id": monitor_id,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
        "last_run": _json(monitor_dir / "last-run.json"),
    }


@mcp.tool()
def hotel_report(
    action: Literal["current", "history"] = "current",
    trip_id: str = "nagoya",
    monitor_id: Literal["marunouchi-booked", "airport-candidate"] = "marunouchi-booked",
    limit: int = 50,
) -> dict[str, Any]:
    """Read current hotel monitor data or quote history. Never consumes API quota."""
    if trip_id != "nagoya":
        return {"status": "unsupported_trip", "trip_id": trip_id, "monitor_id": monitor_id}
    monitor_dir = NAGOYA_HOTELS_DIR / monitor_id
    if action == "current":
        latest = _monitor_json(monitor_dir / "latest.json")
        observations = latest.get("observations", [])
        summary = latest.get("summary") or {
            "total_observations": len(observations),
            "alert_eligible_count": sum(1 for o in observations if o.get("alert_eligible")),
        }
        return {
            "trip_id": trip_id,
            "monitor_id": monitor_id,
            "checked_at": latest.get("checked_at"),
            "status": latest.get("status"),
            "stage": latest.get("stage"),
            "stay": latest.get("stay") or latest.get("effective_request", {}).get("stay"),
            "party": latest.get("party") or latest.get("effective_request", {}).get("party"),
            "execution": {
                "run_id": latest.get("run_id"),
                "coverage": latest.get("coverage"),
            },
            "summary": summary,
            "alerts": [o for o in observations if o.get("alert_eligible")],
            "candidates": observations,
            "quotes": observations,
        }
    rows = _monitor_history(monitor_id)
    return {"trip_id": trip_id, "monitor_id": monitor_id, "history": rows[-max(1, min(limit, 500)):]}


if __name__ == "__main__":
    mcp.run(transport="stdio")
