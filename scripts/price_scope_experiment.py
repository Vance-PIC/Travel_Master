#!/usr/bin/env python3
"""Two pinned booking-option searches to investigate passenger price scope."""
import hashlib
import json
import math
import os
import time
import uuid
from datetime import datetime, timezone

import nagoya_flight_monitor as monitor
from flight_market_test import protected_hashes

CONFIG = monitor.ROOT / "travel/nagoya/price-scope-experiment.json"
OPTION_FIELDS = ("book_with", "price", "local_prices", "option_title", "extensions", "baggage_prices", "marketed_as")


def sanitize(value):
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()
                if k not in ("api_key", "booking_token", "departure_token", "booking_request")}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return value


def validate_selected(selected, cfg=None):
    cfg = cfg or json.loads(CONFIG.read_text(encoding="utf-8"))
    if not isinstance(selected, list) or len(selected) != 2:
        raise ValueError("Expected two selected flight legs")
    for returned, leg in zip(selected, ("outbound", "return")):
        segments = returned.get("flights")
        if not isinstance(segments, list) or len(segments) != 1:
            raise ValueError("Expected nonstop selected leg")
        seg = segments[0]
        wanted = cfg["selected_flights"][leg][0]
        dep, arr = seg.get("departure_airport", {}), seg.get("arrival_airport", {})
        if (monitor.flight_id(seg.get("flight_number", "")) != wanted["flight_number"]
                or dep.get("id") != wanted["departure_id"] or arr.get("id") != wanted["arrival_id"]
                or not str(dep.get("time", "")).startswith(wanted["date"] + " ")
                or seg.get("travel_class") != "Economy"):
            raise ValueError("Returned itinerary does not match the pinned flights")


def record_options(options):
    if not isinstance(options, list):
        raise ValueError("Booking options missing or malformed")
    records = []
    for option in options:
        if not isinstance(option, dict):
            raise ValueError("Malformed booking option")
        record = {"separate_tickets": option.get("separate_tickets", False)}
        for scope in ("together", "departing", "returning"):
            if scope in option:
                if not isinstance(option[scope], dict):
                    raise ValueError("Malformed seller option")
                record[scope] = {k: sanitize(option[scope].get(k)) for k in OPTION_FIELDS}
        records.append(record)
    return records


def indexed_options(options):
    index = {}
    for option in options:
        for scope in ("together", "departing", "returning"):
            fare = option.get(scope)
            if not fare or not fare.get("book_with"):
                continue
            identity = {"scope": scope, "separate_tickets": option.get("separate_tickets", False),
                        "book_with": fare["book_with"], "option_title": fare.get("option_title"),
                        "extensions": sorted(fare.get("extensions") or []),
                        "baggage_prices": sorted(fare.get("baggage_prices") or []),
                        "marketed_as": fare.get("marketed_as")}
            key = json.dumps(identity, sort_keys=True, ensure_ascii=False)
            index.setdefault(key, []).append(fare)
    return index


def valid_price(price):
    return type(price) in (int, float) and math.isfinite(price) and price > 0


def compare_options(a, b):
    left, right = indexed_options(a), indexed_options(b)
    matches, skipped = [], []
    for key in sorted(left.keys() & right.keys()):
        identity = json.loads(key)
        if len(left[key]) != 1 or len(right[key]) != 1:
            skipped.append(dict(identity, reason="ambiguous_duplicate_fare"))
            continue
        pa, pb = left[key][0].get("price"), right[key][0].get("price")
        if not valid_price(pa) or not valid_price(pb):
            skipped.append(dict(identity, reason="missing_or_invalid_price"))
            continue
        local_a = {r["currency"]: r["price"] for r in (left[key][0].get("local_prices") or []) if valid_price(r.get("price"))}
        local_b = {r["currency"]: r["price"] for r in (right[key][0].get("local_prices") or []) if valid_price(r.get("price"))}
        matches.append(dict(identity, a_price_twd=pa, b_price_twd=pb, b_over_a=round(pb / pa, 6),
            local_price_ratios=[{"currency": c, "a_price": local_a[c], "b_price": local_b[c],
                                 "b_over_a": round(local_b[c] / local_a[c], 6)} for c in sorted(local_a.keys() & local_b.keys())]))
    complete = [m for m in matches if m["scope"] == "together" and not m["separate_tickets"]]
    signal = ("no_comparable_round_trip_fare" if not complete else
              "price_increases_with_party_size" if all(m["b_price_twd"] > m["a_price_twd"] for m in complete) else
              "price_unchanged" if all(m["b_price_twd"] == m["a_price_twd"] for m in complete) else "mixed_prices")
    return {"matched_options": matches, "skipped_options": skipped,
            "unmatched_a_count": sum(len(left[k]) for k in left.keys() - right.keys()),
            "unmatched_b_count": sum(len(right[k]) for k in right.keys() - left.keys()),
            "evidence": signal, "price_scope": "unknown", "family_total_twd": None,
            "interpretation": "An increased same-fare price supports party-size-sensitive/party-total pricing for this selected booking offer. It does not prove every market price uses that scope. Child discounts, inventory changes, rounding and sequential timing prevent requiring a ratio of exactly four. No production price scope is changed."}


def run():
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    path = monitor.LATEST.parent / "experiments/price-scope" / run_id / "results.json"
    report = {"schema_version": 1, "checked_at": now.isoformat(timespec="seconds"), "status": "error",
              "planned_searches": 2, "searches_used": 0, "account_calls": 0, "results": [],
              "protected_before": protected_hashes(), "output_path": str(path)}
    stage = "configuration"
    initial_quota = None
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        if cfg["cases"] != [{"label": "A", "adults": 1, "children": 0}, {"label": "B", "adults": 2, "children": 2}]:
            raise ValueError("This experiment requires exactly the two authorized passenger cases")
        key = os.environ.get("SERPAPI_KEY")
        if not key:
            raise ValueError("SERPAPI_KEY not configured")
        common = dict(cfg["common_parameters"], selected_flights_json=json.dumps(cfg["selected_flights"], separators=(",", ":")))
        if any(k in common for k in ("api_key", "adults", "children", "departure_token", "booking_token")):
            raise ValueError("Unexpected common query parameter")
        report.update(query_parameters=common, conditions_key=hashlib.sha256(json.dumps(common, sort_keys=True).encode()).hexdigest())
        for case in cfg["cases"]:
            row = dict(case, status="error", quota_before=None, quota_after=None, selected_flights=[], booking_options=[])
            report["results"].append(row)
            stage = "account_before"
            report["account_calls"] += 1
            before = monitor.quota_state(monitor.request_json({"api_key": key}, monitor.ACCOUNT_BASE))
            row["quota_before"] = before
            initial_quota = initial_quota or before
            if monitor.effective_budget(initial_quota, before, report["searches_used"])["tier"] == "preserve":
                row["status"] = "quota_preserved"
                report["status"] = "quota_limited"
                break
            stage = "selected_flights_search"
            report["searches_used"] += 1
            started = time.perf_counter()
            failure = None
            try:
                data = monitor.request_json(dict(common, api_key=key, adults=case["adults"], children=case["children"]), timeout=120)
                row["response_time_seconds"] = round(time.perf_counter() - started, 6)
                stage = "selected_flights_parse"
                # Save the requested evidence even when itinerary validation fails.
                row.update(selected_flights=sanitize(data.get("selected_flights")),
                           booking_options=record_options(data.get("booking_options")),
                           baggage_prices=sanitize(data.get("baggage_prices")),
                           search_metadata={k: (data.get("search_metadata") or {})[k] for k in
                               ("id", "status", "created_at", "processed_at", "total_time_taken") if k in (data.get("search_metadata") or {})})
                validate_selected(row["selected_flights"], cfg)
                row["status"] = "ok"
            except Exception as exc:
                failure = {"error_type": type(exc).__name__, "error_stage": stage,
                           "error": "Price-scope experiment failed; no additional flight requests or production writes were made."}
                row["response_time_seconds"] = round(time.perf_counter() - started, 6)
            stage = "account_after"
            report["account_calls"] += 1
            after = monitor.quota_state(monitor.request_json({"api_key": key}, monitor.ACCOUNT_BASE))
            row.update(quota_after=after, actual_usage_delta=after["usage"] - before["usage"])
            if failure:
                row.update(failure, status="error")
                break
        else:
            report["status"] = "ok"
            report["comparison"] = compare_options(report["results"][0]["booking_options"], report["results"][1]["booking_options"])
    except Exception as exc:
        report.update(status="error", error_type=type(exc).__name__, error_stage=stage,
                      error="Experiment could not complete; inspect sanitized stage. Production files were not written.")
    report["protected_after"] = protected_hashes()
    report["production_files_unchanged"] = report["protected_before"] == report["protected_after"]
    if not report["production_files_unchanged"]:
        report.update(status="error", error_stage="production_integrity")
    monitor.atomic_json(path, report)
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] in ("ok", "quota_limited") else 2)
