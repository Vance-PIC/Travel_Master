#!/usr/bin/env python3
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

OUTBOUND_DATE = "2027-07-11"
INBOUND_DATE = "2027-07-18"
ORIGIN = "TPE"
DESTINATION = "NGO"

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "travel/nagoya/flights/latest.json"
HISTORY = ROOT / "travel/nagoya/flights/history.csv"
DEBUG_DIR = ROOT / "travel/nagoya/flights/debug"

FULL_SERVICE_NAMES = {
    "China Airlines": "CI",
    "Cathay Pacific": "CX",
    "STARLUX Airlines": "JX",
    "EVA Air": "BR",
    "ANA": "NH",
    "All Nippon Airways": "NH",
    "Japan Airlines": "JL",
}

def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def compact(s):
    return re.sub(r"\s+", " ", s or "").strip()

def parse_money(text):
    if not text:
        return None
    m = re.search(r"(?:NT\$|TWD\s*)?([0-9][0-9,]{3,})", text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None

def save_debug(page):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    (DEBUG_DIR / "google-flights.html").write_text(page.content(), encoding="utf-8")
    (DEBUG_DIR / "google-flights.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
    page.screenshot(path=str(DEBUG_DIR / "google-flights.png"), full_page=True)

def search_google_flights(page):
    query = (
        "Flights from TPE to NGO on July 11 2027 returning July 18 2027 "
        "for 2 adults and 2 children nonstop"
    )
    url = "https://www.google.com/travel/flights?hl=zh-TW&curr=TWD"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)

    # Prefer Google's generic travel search box if present.
    candidates = [
        'input[placeholder*="搜尋"]',
        'input[aria-label*="搜尋"]',
        'input[placeholder*="Search"]',
        'input[aria-label*="Search"]',
    ]
    box = None
    for sel in candidates:
        loc = page.locator(sel).first
        if loc.count() > 0:
            try:
                if loc.is_visible():
                    box = loc
                    break
            except Exception:
                pass
    if box is None:
        raise RuntimeError("Google Flights search box not found")

    box.fill(query)
    box.press("Enter")
    page.wait_for_timeout(10000)

    # Wait for the page to settle and expose fare cards.
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(5000)

def extract_candidates(page):
    body_text = page.locator("body").inner_text()
    lines = [compact(x) for x in body_text.splitlines() if compact(x)]

    rows = []
    # Heuristic parser: Google Flights card text generally exposes airline name,
    # times, airports, duration/stops, and a price within a nearby text block.
    for name, code in FULL_SERVICE_NAMES.items():
        idxs = [i for i, line in enumerate(lines) if name.lower() in line.lower()]
        for idx in idxs[:8]:
            block = " | ".join(lines[max(0, idx-4): min(len(lines), idx+14)])
            if ORIGIN not in block or DESTINATION not in block:
                continue
            if not any(k in block.lower() for k in ["直飛", "nonstop", "non-stop"]):
                continue
            price = parse_money(block)
            if price is None:
                continue

            time_matches = re.findall(r"\b([01]?\d|2[0-3]):[0-5]\d\b", block)
            departure_time = time_matches[0] if time_matches else None
            arrival_time = time_matches[1] if len(time_matches) > 1 else None

            rows.append({
                "airline": name,
                "airline_iata": code,
                "search_total_twd": price,
                "outbound_departure": departure_time,
                "outbound_arrival": arrival_time,
                "raw_text": block[:1200],
                "time_preference_match": bool(departure_time and departure_time < "12:00"),
            })

    # Dedupe by airline + price + first visible departure time.
    dedup = {}
    for r in rows:
        key = (r["airline_iata"], r["search_total_twd"], r["outbound_departure"])
        dedup[key] = r

    return sorted(
        dedup.values(),
        key=lambda r: (
            0 if r["time_preference_match"] else 1,
            r["search_total_twd"],
        ),
    )

def write_results(rows, status, checked_at):
    latest = {
        "schema_version": 3,
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
        "source": "Google Flights web (Playwright)",
        "source_validation": "web_scrape_unverified",
        "options": rows[:20],
        "notes": (
            "No API token used. Browser automation against Google Flights. "
            "Selectors and rendered text may change. Price/baggage/fare conditions "
            "must be independently verified before booking."
        ),
    }
    LATEST.parent.mkdir(parents=True, exist_ok=True)
    LATEST.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    header = [
        "checked_at","status","source","airline","airline_iata",
        "search_total_twd","outbound_departure","outbound_arrival",
        "time_preference_match","notes"
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
                    "source": "Google Flights web (Playwright)",
                    "airline": r["airline"],
                    "airline_iata": r["airline_iata"],
                    "search_total_twd": r["search_total_twd"],
                    "outbound_departure": r["outbound_departure"],
                    "outbound_arrival": r["outbound_arrival"],
                    "time_preference_match": r["time_preference_match"],
                    "notes": "web_scrape_unverified",
                })
        else:
            w.writerow({
                "checked_at": checked_at,
                "status": status,
                "source": "Google Flights web (Playwright)",
                "airline": "",
                "airline_iata": "",
                "search_total_twd": "",
                "outbound_departure": "",
                "outbound_arrival": "",
                "time_preference_match": False,
                "notes": "No parseable matching fare rows",
            })

def main():
    checked_at = now_iso()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            viewport={"width": 1440, "height": 1600},
        )
        page = context.new_page()
        try:
            search_google_flights(page)
            save_debug(page)
            rows = extract_candidates(page)
            status = "ok" if rows else "no_parseable_results"
            write_results(rows, status, checked_at)
            print(f"Parsed {len(rows)} candidate rows")
            return 0 if rows else 3
        except Exception as exc:
            try:
                save_debug(page)
            except Exception:
                pass
            print(f"Google Flights browser extraction failed: {exc}", file=sys.stderr)
            return 2
        finally:
            browser.close()

if __name__ == "__main__":
    raise SystemExit(main())
