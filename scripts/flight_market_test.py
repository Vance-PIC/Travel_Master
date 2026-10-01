#!/usr/bin/env python3
"""Isolated SerpApi deep_search experiment; never writes monitoring state."""
import argparse
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import nagoya_flight_monitor as monitor


def protected_hashes():
    names = ("latest.json", "history.csv", "itinerary_history.csv", "last-run.json")
    return {name: hashlib.sha256((monitor.LATEST.parent / name).read_bytes()).hexdigest()
            if (monitor.LATEST.parent / name).exists() else None for name in names}


def compare_results(results):
    a, b = results
    false = {r["flight_key"]: r for r in a["flights"]}
    true = {r["flight_key"]: r for r in b["flights"]}
    return {"added_flights": sorted(true.keys() - false.keys()),
            "removed_flights": sorted(false.keys() - true.keys()),
            "flight_count_difference": b["flight_count"] - a["flight_count"],
            "response_time_difference_seconds": round(b["response_time_seconds"] - a["response_time_seconds"], 6),
            "price_differences": [{"flight_key": n, "false_price_twd": false[n]["displayed_price_twd"],
                "true_price_twd": true[n]["displayed_price_twd"],
                "difference_twd": true[n]["displayed_price_twd"] - false[n]["displayed_price_twd"]}
                for n in sorted(false.keys() & true.keys())],
            "limitations": "Sequential observations; cache and market changes may affect timing and prices. Account counters can lag. This is a market-only comparison, not return itinerary prices."}


def run(deep_search=False, compare=False, output_dir=None):
    experiments = (monitor.LATEST.parent / "experiments").resolve()
    output_dir = Path(output_dir).resolve() if output_dir is not None else experiments / "deep-search"
    if not output_dir.is_relative_to(experiments):
        raise ValueError("Experiment output must stay inside the experiments directory")
    if type(deep_search) is not bool or type(compare) is not bool:
        raise ValueError("Test flags must be boolean")
    checked = datetime.now(timezone.utc)
    run_id = checked.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    output_path = output_dir / run_id / "results.json"
    report = {"schema_version": 1, "mode": "ab_comparison" if compare else "single_scan",
              "checked_at": checked.isoformat(timespec="seconds"), "status": "error",
              "planned_searches": 2 if compare else 1, "searches_used": 0, "account_calls": 0,
              "results": [], "output_path": str(output_path), "protected_before": protected_hashes()}
    stage = "configuration"
    starting_quota = None
    try:
        cfg = json.loads(monitor.CONFIG.read_text(encoding="utf-8"))
        if cfg["cabin_class"] != "economy" or not cfg["nonstop_only"]:
            raise ValueError("The executor requires nonstop Economy")
        key = os.environ.get("SERPAPI_KEY")
        if not key:
            raise ValueError("SERPAPI_KEY not configured")
        base = monitor.market_scan_params(cfg, key)
        public_params = {k: v for k, v in base.items() if k != "api_key"}
        report["query_parameters"] = public_params
        report["conditions_key"] = hashlib.sha256(json.dumps(public_params, sort_keys=True).encode()).hexdigest()
        for enabled in ([False, True] if compare else [deep_search]):
            row = {"deep_search": enabled, "status": "error", "searches_used": 0,
                   "quota_before": None, "quota_after": None, "response_time_seconds": None,
                   "raw_offer_count": None, "flight_count": None, "flights": []}
            report["results"].append(row)
            stage = "account_before"
            report["account_calls"] += 1
            before = monitor.quota_state(monitor.request_json({"api_key": key}, monitor.ACCOUNT_BASE))
            row["quota_before"] = before
            if starting_quota is None:
                starting_quota = before
            budget = monitor.effective_budget(starting_quota, before, report["searches_used"])
            if budget["tier"] == "preserve":
                row["status"] = "quota_preserved"
                report["status"] = "quota_limited"
                break
            stage = "market_scan"
            row["searches_used"] = 1
            report["searches_used"] += 1
            started = time.perf_counter()
            failure = None
            try:
                data = monitor.request_json(dict(base, deep_search=str(enabled).lower()), timeout=120)
                row["response_time_seconds"] = round(time.perf_counter() - started, 6)
                stage = "market_parse"
                offers = monitor.result_groups(data)
                flights = {}
                for item in offers:
                    candidate = monitor.candidate(item, cfg)
                    if candidate:
                        number = monitor.flight_id(candidate["outbound_flight"])
                        old = flights.get(number)
                        if old is None or candidate["displayed_price_twd"] < old["displayed_price_twd"]:
                            # Discard token availability: experiments never expand tokens.
                            candidate.pop("departure_token_available", None)
                            flights[number] = dict(candidate, flight_key=number)
                metadata = data.get("search_metadata") or {}
                row.update(status="ok", raw_offer_count=len(offers), flight_count=len(flights),
                           flights=list(flights.values()),
                           search_metadata={k: metadata[k] for k in
                               ("id", "status", "created_at", "processed_at", "total_time_taken") if k in metadata})
            except Exception as exc:
                row["response_time_seconds"] = round(time.perf_counter() - started, 6)
                failure = {"error_type": type(exc).__name__, "error_stage": stage,
                           "error": "Market experiment failed; production data was not modified."}
            # Account observation still runs after a failed market request; no paid retries.
            stage = "account_after"
            report["account_calls"] += 1
            after = monitor.quota_state(monitor.request_json({"api_key": key}, monitor.ACCOUNT_BASE))
            row.update(quota_after=after, actual_usage_delta=after["usage"] - before["usage"])
            if failure:
                row.update(failure, status="error")
                report["status"] = "error"
                break
        else:
            report["status"] = "ok"
        if compare and report["status"] == "ok":
            report["comparison"] = compare_results(report["results"])
    except Exception as exc:
        report.update(status="error", error_type=type(exc).__name__, error_stage=stage,
                      error="Market experiment failed; inspect the sanitized stage. Production data was not modified.")
    report["protected_after"] = protected_hashes()
    report["production_files_unchanged"] = report["protected_before"] == report["protected_after"]
    if not report["production_files_unchanged"]:
        report.update(status="error", error_stage="production_integrity",
                      error="Production files changed during the test. No restoration was attempted.")
    monitor.atomic_json(output_path, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deep-search", choices=("true", "false"), default="false")
    parser.add_argument("--compare", action="store_true", help="Run false then true with identical hard parameters")
    args = parser.parse_args()
    result = run(deep_search=args.deep_search == "true", compare=args.compare)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] in ("ok", "quota_limited") else 2)
