#!/usr/bin/env python3
import argparse
import csv
import hashlib
import math
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
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

def request_json(params, endpoint=API_BASE, timeout=45):
    url = endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Travel_Master flight monitor"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    if not isinstance(data, dict) or data.get("error"):
        raise RuntimeError("Invalid response or SerpApi error")
    return data

def airline_code(flight_number):
    if not flight_number:
        return None
    return flight_number.replace(" ", "")[:2]

def baggage_status(item):
    # API extension text is not evidence of checked-baggage entitlement.
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
    if not code or not dep.get("id") or not arr.get("id") or not seg.get("travel_class"):
        raise ValueError("Required segment fields missing")
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
    if type(price) not in (int, float) or not math.isfinite(price) or price <= 0:
        raise ValueError("Invalid displayed price")
    prefix = "inbound" if inbound else "outbound"
    match = preference(arr.get("time") if inbound else dep.get("time"),
                       cfg["preferences"]["inbound_arrival_before" if inbound else "outbound_before"])
    return {"airline": seg.get("airline"), "airline_iata": code,
            prefix + "_flight": seg.get("flight_number"),
            prefix + "_departure": dep.get("time"), prefix + "_arrival": arr.get("time"),
            "displayed_price_twd": price, "price_scope": "unknown", "family_total_twd": None,
            "currency": "TWD", "baggage_status": baggage_status(item),
            "inbound_preference_match": None,
            prefix + "_preference_match": match,
            "time_preference_match": False if match is False else None,
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
    return reasons


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def flight_id(value):
    return value.replace(" ", "").upper()


def route_key(cfg):
    fields = ("origin", "destination", "outbound_date", "inbound_date", "passengers",
              "cabin_class", "nonstop_only", "currency", "market", "locale", "full_service_airlines")
    payload = json.dumps({k: cfg[k] for k in fields}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def refresh_due(stamp, now, days):
    if not stamp:
        return True
    parsed = datetime.fromisoformat(stamp)
    if parsed.tzinfo is None:
        raise ValueError("Refresh timestamp lacks timezone")
    return now - parsed >= timedelta(days=days)


def effective_budget(before, after, searches):
    return quota_state({"this_month_usage": max(after["usage"], before["usage"] + searches),
                        "total_searches_left": max(0, min(after["remaining"], before["remaining"] - searches))})


def select_expansions(market, tokens, refreshed, cfg, mode, now, tier, pending=None):
    required = cfg["full_query_outbounds"]
    days = cfg["reduced_refresh_days"] if tier == "reduced" else cfg["itinerary_refresh_days"]
    by_flight = {flight_id(r["outbound_flight"]): r for r in market}
    wanted = {n: list(reasons) for n, reasons in (pending or {}).items()} if mode == "monitor_query" else {}
    for number in required:
        if mode == "full_query" or refresh_due(refreshed.get(number), now, days):
            wanted[number] = ["full_query" if mode == "full_query" else "itinerary_refresh"]
    if mode == "monitor_query":
        for number, row in by_flight.items():
            # Unknown prior markets do not justify expanding every flight.
            triggers = [x for x in row["deep_search_triggers"] if x != "initial_baseline"]
            if triggers:
                wanted.setdefault(number, []).extend(triggers)
    available = [n for n in wanted if n in by_flight and n in tokens]
    # Rotate overdue outbound checks at reduced quota; substantial drops have priority.
    available.sort(key=lambda n: ("drop_5_percent" not in wanted[n],
                                 refreshed.get(n, ""), required.index(n) if n in required else len(required),
                                 by_flight[n]["displayed_price_twd"]))
    if tier in ("market_only", "preserve"):
        limit = 0
    elif tier == "reduced":
        limit = cfg["reduced_max_expansions"]
    elif mode == "full_query" or any("itinerary_refresh" in wanted[n] for n in available):
        limit = cfg["full_max_expansions"]
    else:
        limit = cfg["monitor_max_expansions"]
    return available[:limit], wanted, limit


def read_history(path):
    if not path.exists():
        return [], []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), reader.fieldnames or []


def itinerary_lows(history, trip_key):
    lows = {}
    for row in history:
        if row.get("route_key") != trip_key or row.get("status") != "observed":
            continue
        if row.get("price_scope") not in ("unknown", "family_total") or row.get("currency") != "TWD":
            continue
        price = float(row["displayed_price_twd"])
        if not math.isfinite(price) or price <= 0:
            raise ValueError("Invalid historical itinerary price")
        key = row["itinerary_key"]
        lows[key] = min(lows.get(key, price), price)
    return lows


def build_itinerary(outbound, ret, checked_at, previous, lows, cfg):
    row = dict(outbound)
    row.update({k: v for k, v in ret.items() if k.startswith("inbound_")})
    row.update(inbound_airline_iata=ret["airline_iata"], displayed_price_twd=ret["displayed_price_twd"],
               baggage_status="unknown", checked_at=checked_at, observed_this_run=True,
               observation_status="observed", route_key=route_key(cfg))
    flags = [row["outbound_preference_match"], row["inbound_preference_match"]]
    row["time_preference_match"] = False if False in flags else (None if None in flags else True)
    key = flight_id(row["outbound_flight"]) + "+" + flight_id(row["inbound_flight"])
    row["itinerary_key"] = key
    old = previous.get(key)
    old_price = old.get("displayed_price_twd") if old else None
    low = lows.get(key, old_price)
    changes = []
    if old_price is None:
        changes.append("new_itinerary")
    elif row["displayed_price_twd"] != old_price:
        changes.append("price_drop" if row["displayed_price_twd"] < old_price else "price_increase")
        if row["displayed_price_twd"] <= old_price * (1 - cfg["drop_fraction"]):
            changes.append("drop_5_percent")
    if low is not None and row["displayed_price_twd"] < low:
        changes.append("new_low")
    row.update(previous_displayed_price_twd=old_price, price_changes=changes,
               historical_low_twd=min(low, row["displayed_price_twd"]) if low is not None else row["displayed_price_twd"])
    return row


def stage_csv(path, observations, header):
    old, old_header = read_history(path)
    header = list(dict.fromkeys(header + old_header))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(old + observations)
    return temp


def booking_reasons(row, cfg, purchase=False):
    if purchase:
        return ["purchase"]
    if not row.get("observed_this_run"):
        return []
    reasons = [r for r in row.get("price_changes", []) if r in ("new_low", "drop_5_percent")]
    if row["displayed_price_twd"] <= cfg["family_target_twd"] * (1 + cfg["target_margin_fraction"]):
        reasons.append("near_target")
    return reasons


def booking_params(base, row, cfg):
    segments = {}
    for prefix, date, origin, destination in (
            ("outbound", cfg["outbound_date"], cfg["origin"], cfg["destination"]),
            ("inbound", cfg["inbound_date"], cfg["destination"], cfg["origin"])):
        segments["return" if prefix == "inbound" else prefix] = [{"flight_number": flight_id(row[prefix + "_flight"]),
                             "departure_id": origin, "arrival_id": destination, "date": date}]
    return dict(base, selected_flights_json=json.dumps(segments, separators=(",", ":")))


def verify_booking(data, row, cfg, stamp):
    if cfg["passengers"] != {"adults": 2, "children": 2} or cfg["currency"] != "TWD":
        raise ValueError("Family verification requires 2A2C TWD")
    echoed = data.get("search_parameters", {})
    for key, expected in (("adults", 2), ("children", 2), ("currency", "TWD")):
        if key in echoed and str(echoed[key]) != str(expected):
            raise ValueError("Booking passenger/currency mismatch")
    selected = data.get("selected_flights")
    if not isinstance(selected, list) or len(selected) != 2:
        raise ValueError("Selected itinerary missing")
    for prefix, group, origin, destination, date in (
            ("outbound", selected[0], cfg["origin"], cfg["destination"], cfg["outbound_date"]),
            ("inbound", selected[1], cfg["destination"], cfg["origin"], cfg["inbound_date"])):
        flights = group.get("flights", [])
        if len(flights) != 1:
            raise ValueError("Selected flight is not nonstop")
        seg = flights[0]
        dep, arr = seg.get("departure_airport", {}), seg.get("arrival_airport", {})
        if (flight_id(seg.get("flight_number", "")) != flight_id(row[prefix + "_flight"])
                or dep.get("id") != origin or arr.get("id") != destination
                or not str(dep.get("time", "")).startswith(date + " ")
                or dep.get("time") != row[prefix + "_departure"]
                or seg.get("travel_class") != "Economy"):
            raise ValueError("Selected itinerary mismatch")
    options = data.get("booking_options")
    if not isinstance(options, list):
        raise ValueError("Booking options missing")
    for group in options:
        option = group.get("together") or {}
        price = option.get("price")
        marketed = option.get("marketed_as")
        if (group.get("separate_tickets") or option.get("separate_tickets") or not option.get("book_with")
                or type(price) not in (int, float) or not math.isfinite(price)
                or price != row["displayed_price_twd"]
                or (marketed and [flight_id(n) for n in marketed] !=
                    [flight_id(row["outbound_flight"]), flight_id(row["inbound_flight"])])):
            continue
        return dict(source="SerpApi Booking Options", verified_at=stamp,
                    itinerary_key=row["itinerary_key"], quote_checked_at=row["checked_at"],
                    passengers=cfg["passengers"], currency="TWD",
                    **{k: option.get(k) for k in ("book_with", "price", "local_prices", "option_title",
                                                "extensions", "baggage_prices", "marketed_as")})
    return None


def persist(latest, observed, removed, cfg):
    attempt = {k: latest[k] for k in ("checked_at", "status", "searches_used", "quota_after")}
    fields = HISTORY_HEADER + ["record_type", "mode", "searches_used", "quota_status", "quota_usage",
                              "quota_remaining", "outbound_preference_match", "inbound_preference_match",
                              "inbound_airline_iata", "deep_search_triggers", "itinerary_key", "route_key",
                              "refresh_reasons", "price_changes", "previous_displayed_price_twd", "historical_low_twd",
                              "price_verification", "baggage_verification"]
    def history_row(row, kind, status):
        result = dict(row, checked_at=attempt["checked_at"], status=status, record_type=kind,
                      mode=latest["mode"], searches_used=latest["searches_used"],
                      quota_status=latest["quota_after"]["tier"], quota_usage=latest["quota_after"]["usage"],
                      quota_remaining=latest["quota_after"]["remaining"], route_key=route_key(cfg),
                      source="SerpApi Google Flights")
        for key in ("deep_search_triggers", "refresh_reasons", "price_changes"):
            result[key] = ";".join(result.get(key, []))
        for key in ("price_verification", "baggage_verification"):
            if result.get(key):
                result[key] = json.dumps(result[key], ensure_ascii=False)
        return result
    market_rows = [history_row(r, "market", "observed") for r in latest["market_candidates"]]
    if not market_rows:
        market_rows = [history_row({}, "run", latest["status"])]
    stages = [(stage_csv(HISTORY, market_rows, fields), HISTORY)]
    itinerary_path = LATEST.parent / "itinerary_history.csv"
    itinerary_rows = [history_row(r, "itinerary", "observed") for r in observed]
    itinerary_rows += [history_row(r, "itinerary", "not_returned") for r in removed]
    itinerary_rows += [history_row(r, "verification", "verified") for r in latest["itineraries"]
                       if not r.get("observed_this_run")
                       and r.get("price_verification", {}).get("verified_at") == latest["checked_at"]]
    if itinerary_rows:
        stages.append((stage_csv(itinerary_path, itinerary_rows, fields), itinerary_path))
    # Finish all parsing and stage every CSV before publishing the new snapshot.
    for temp, target in stages:
        temp.replace(target)
    atomic_json(LATEST, latest)


def market_scan_params(cfg, key):
    return {"engine": "google_flights", "departure_id": cfg["origin"],
            "arrival_id": cfg["destination"], "outbound_date": cfg["outbound_date"],
            "return_date": cfg["inbound_date"], "type": 1, "travel_class": 1,
            "adults": cfg["passengers"]["adults"], "children": cfg["passengers"]["children"],
            "stops": 1, "currency": cfg["currency"], "gl": cfg["market"].lower(),
            "hl": cfg["locale"].lower(), "include_airlines": ",".join(cfg["full_service_airlines"]),
            "api_key": key}


def main(mode="monitor_query", now=None, purchase_itinerary=None):
    searches = account_calls = 0
    before = after = None
    stage = "configuration"
    now = now or datetime.now(timezone.utc)
    checked_at = now.isoformat(timespec="seconds")
    attempt = {"checked_at": checked_at, "status": "error", "mode": mode}
    try:
        if mode not in ("full_query", "monitor_query"):
            raise ValueError("Unsupported execution mode")
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        booking_limit = cfg.get("booking_verifications_per_run", 1)
        if type(booking_limit) is not int or booking_limit not in (0, 1):
            raise ValueError("Booking verification limit must be 0 or 1")
        if cfg["cabin_class"] != "economy" or not cfg["nonstop_only"]:
            raise ValueError("This executor requires nonstop Economy")
        if not 3 <= cfg["itinerary_refresh_days"] <= cfg["reduced_refresh_days"] <= 5:
            raise ValueError("Refresh interval must remain within 3 to 5 days")
        key = os.environ.get("SERPAPI_KEY")
        if not key:
            raise ValueError("SERPAPI_KEY is not configured")
        previous = json.loads(LATEST.read_text(encoding="utf-8")) if LATEST.exists() else {}
        previous_route = previous.get("route")
        if previous_route and route_key(previous_route) != route_key(cfg):
            previous = {}
        prior_market = previous.get("market_candidates", [])
        old_itineraries = previous.get("itineraries", [])
        # v1 return options remain archived in history; do not pretend they form a v2 baseline.
        previous_rows = {r["itinerary_key"]: r for r in old_itineraries}
        historic, _ = read_history(LATEST.parent / "itinerary_history.csv")
        low_itineraries = itinerary_lows(historic, route_key(cfg))
        for row in historic:
            if (row.get("route_key") == route_key(cfg) and row.get("status") == "observed"
                    and row.get("price_scope") in ("unknown", "family_total") and row.get("currency") == "TWD"):
                previous_rows[row["itinerary_key"]] = dict(row, displayed_price_twd=float(row["displayed_price_twd"]))
        refreshed = dict(previous.get("outbound_refresh", {}))
        base = market_scan_params(cfg, key)
        stage = "account_before"
        account_calls += 1
        before = quota_state(request_json({"api_key": key}, ACCOUNT_BASE))
        if before["tier"] == "preserve":
            attempt.update(status="quota_preserved", quota_before=before, searches_used=0,
                           planned_searches=0, account_calls=account_calls)
            atomic_json(LATEST.parent / "last-run.json", attempt)
            print(json.dumps(attempt))
            return 0
        stage = "market_scan"
        searches += 1
        first = request_json(base)
        by_outbound, tokens = {}, {}
        for item in result_groups(first):
            row = candidate(item, cfg)
            if row:
                number = flight_id(row["outbound_flight"])
                old = by_outbound.get(number)
                if old is None or row["displayed_price_twd"] < old["displayed_price_twd"]:
                    by_outbound[number] = row
                    tokens.pop(number, None)
                    if item.get("departure_token"):
                        tokens[number] = item["departure_token"]
        market = list(by_outbound.values())
        lows = {flight_id(k): v for k, v in previous.get("market_price_lows", {}).items()}
        old_market = [dict(r, outbound_flight=flight_id(r["outbound_flight"])) for r in prior_market]
        for old in old_market:
            number, price = old["outbound_flight"], old.get("displayed_price_twd")
            if type(price) in (int, float):
                lows[number] = min(lows.get(number, price), price)
        for row in market:
            normalized = dict(row, outbound_flight=flight_id(row["outbound_flight"]))
            row["deep_search_triggers"] = deep_reasons(normalized, old_market, lows, cfg)
        stage = "account_after_market"
        account_calls += 1
        after = quota_state(request_json({"api_key": key}, ACCOUNT_BASE))
        budget = effective_budget(before, after, searches)
        pending = dict(previous.get("pending_deep_search", {}))
        selected, wanted, _ = select_expansions(market, tokens, refreshed, cfg, mode, now, budget["tier"], pending)
        attempt["planned_searches"] = 1 + len(selected)
        observed, completed = [], []
        for number in selected:
            budget = effective_budget(before, after, searches)
            if budget["tier"] in ("market_only", "preserve"):
                break
            if budget["tier"] == "reduced" and len(completed) >= cfg["reduced_max_expansions"]:
                break
            stage = "deep_search:" + number
            searches += 1
            response = request_json(dict(base, departure_token=tokens[number]))
            returns = {}
            for item in result_groups(response):
                ret = candidate(item, cfg, inbound=True)
                if ret:
                    row = build_itinerary(by_outbound[number], ret, checked_at, previous_rows, low_itineraries, cfg)
                    row["refresh_reasons"] = wanted[number]
                    old = returns.get(row["itinerary_key"])
                    if old is None or row["displayed_price_twd"] < old["displayed_price_twd"]:
                        returns[row["itinerary_key"]] = row
            observed.extend(returns.values())
            completed.append(number)
            refreshed[number] = checked_at
            stage = "account_after_deep:" + number
            account_calls += 1
            after = quota_state(request_json({"api_key": key}, ACCOUNT_BASE))
        fresh_keys = {r["itinerary_key"] for r in observed}
        budget = effective_budget(before, after, searches)
        removed = [dict(r, displayed_price_twd=None, price_changes=["not_returned"])
                   for r in old_itineraries if flight_id(r["outbound_flight"]) in completed and r["itinerary_key"] not in fresh_keys]
        retained = [dict(r, observed_this_run=False,
                         observation_status="retained" if flight_id(r["outbound_flight"]) in by_outbound else "outbound_not_observed")
                    for r in old_itineraries if flight_id(r["outbound_flight"]) not in completed]
        itineraries = retained + observed
        booking_checks = []
        eligible = [(r, booking_reasons(r, cfg, purchase_itinerary == r["itinerary_key"]))
                    for r in itineraries]
        eligible = [(r, reasons) for r, reasons in eligible if reasons]
        eligible.sort(key=lambda pair: ("purchase" not in pair[1], pair[0]["displayed_price_twd"]))
        if purchase_itinerary and not any(r["itinerary_key"] == purchase_itinerary for r in itineraries):
            booking_checks.append({"itinerary_key": purchase_itinerary, "status": "itinerary_unavailable"})
        for index, (row, reasons) in enumerate(eligible):
            budget = effective_budget(before, after, searches)
            check = dict(itinerary_key=row["itinerary_key"], reasons=reasons, status="deferred",
                         quota_before=after)
            booking_checks.append(check)
            if index >= booking_limit or budget["tier"] in ("market_only", "preserve"):
                check["deferred_reason"] = "run_limit" if index >= booking_limit else "quota"
                continue
            attempt["planned_searches"] += 1
            stage = "booking_options:" + row["itinerary_key"]
            row.update(price_scope="unknown", family_total_twd=None, baggage_status="unknown")
            row.pop("price_verification", None)
            row.pop("baggage_verification", None)
            searches += 1
            try:
                evidence = verify_booking(request_json(booking_params(base, row, cfg)), row, cfg, checked_at)
                check["status"] = "verified" if evidence else "price_not_matched"
                if evidence:
                    row.update(price_scope="family_total", family_total_twd=row["displayed_price_twd"],
                               price_verification=evidence,
                               baggage_status="booking_option_verified" if evidence.get("baggage_prices") else "unknown",
                               baggage_verification=evidence if evidence.get("baggage_prices") else None)
            except Exception as exc:
                check.update(status="error", error_type=type(exc).__name__,
                             error="Booking verification failed; raw quote remains unchanged.")
            stage = "account_after_booking"
            account_calls += 1
            after = quota_state(request_json({"api_key": key}, ACCOUNT_BASE))
            check["quota_after"] = after
        budget = effective_budget(before, after, searches)
        for row in market:
            number, price = flight_id(row["outbound_flight"]), row["displayed_price_twd"]
            lows[number] = min(lows.get(number, price), price)
        required = cfg["full_query_outbounds"]
        missing = [n for n in required if n not in by_outbound or n not in tokens]
        deferred = [n for n in wanted if n not in completed]
        pending.update({n: list(dict.fromkeys(wanted[n])) for n in deferred})
        for number in completed:
            pending.pop(number, None)
        interval = cfg["reduced_refresh_days"] if budget["tier"] == "reduced" else cfg["itinerary_refresh_days"]
        baseline_complete = not missing and all(
            any(flight_id(r["outbound_flight"]) == n for r in itineraries)
            and not refresh_due(refreshed.get(n), now, interval) for n in required)
        attempt.update(status="ok" if market else "no_matching_offers", searches_used=searches,
                       api_searches_used=searches, account_calls=account_calls, quota_before=before,
                       quota_after=after, actual_usage_delta=after["usage"] - before["usage"],
                       monitoring_mode="market_plus_return" if completed else "market_only",
                       refreshed_outbounds=completed, deferred_outbounds=deferred,
                       missing_required_outbounds=missing, baseline_complete=baseline_complete,
                       booking_verification_checks=booking_checks,
                       refresh_complete=bool(wanted) and not deferred and not missing)
        latest = dict(attempt, schema_version=7, skill_version=2, route=cfg,
                      source="SerpApi Google Flights", source_validation="single_source_unverified",
                      market_candidates=market, itineraries=itineraries,
                      options=observed, market_price_lows=lows, outbound_refresh=refreshed,
                      pending_deep_search=pending,
                      itinerary_refresh_days=cfg["reduced_refresh_days"] if budget["tier"] == "reduced" else cfg["itinerary_refresh_days"],
                      notes="Raw market/itinerary prices remain unchanged. Only exact 2A2C Booking Options matches verify that specific quote. Baggage evidence is seller-specific literal text. Historical rows are not backfilled.")
        stage = "persistence"
        persist(latest, observed, removed, cfg)
        atomic_json(LATEST.parent / "last-run.json", attempt)
        print(json.dumps(dict(attempt, airlines=sorted({r["airline_iata"] for r in market}),
                              itinerary_count=len(itineraries), newly_observed_itineraries=len(observed))))
        return 0
    except Exception as exc:
        attempt.update(error_type=type(exc).__name__, error_stage=stage,
                       error="Monitoring failed; last valid snapshot preserved. Inspect stage and configuration.",
                       searches_used=searches, account_calls=account_calls, quota_before=before, quota_after=after)
        atomic_json(LATEST.parent / "last-run.json", attempt)
        print(json.dumps(attempt), file=sys.stderr)
        return 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Budget-aware flight monitoring")
    parser.add_argument("--mode", choices=("full_query", "monitor_query"), default="monitor_query")
    parser.add_argument("--purchase-itinerary", help="Explicit purchase preparation, e.g. CI154+CI151")
    args = parser.parse_args()
    raise SystemExit(main(mode=args.mode, purchase_itinerary=args.purchase_itinerary))
