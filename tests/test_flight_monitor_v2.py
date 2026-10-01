import csv
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import test_nagoya_flight_monitor as legacy

CFG, m, offer = legacy.CFG, legacy.m, legacy.offer


def flight(number, price=60000, inbound=False, time="07:30"):
    item = offer(number[:2], price, time, inbound)
    item["flights"][0]["flight_number"] = number
    return item


class V2Tests(unittest.TestCase):
    account = legacy.MonitorTests.account

    def setUp(self):
        legacy.MonitorTests.setUp(self)
        self.now = datetime(2026, 10, 1, 3, tzinfo=timezone.utc)
        self.items = [flight("CI154"), flight("CX530", 80000),
                      flight("JX838", 90000, time="14:55"), flight("CI150", 50000, time="17:15")]

    def v2_run(self, responses, mode="monitor_query"):
        with patch.dict(m.os.environ, {"SERPAPI_KEY": "fake-secret"}), patch.object(m, "request_json", side_effect=responses) as req:
            result = m.main(mode=mode, now=self.now)
        return result, req

    def seed_v2(self, age_days=1):
        stamp = (self.now - timedelta(days=age_days)).isoformat()
        market = [m.candidate(item, CFG) for item in self.items]
        rows = [{"itinerary_key": "CI154+CI151", "outbound_flight": "CI154", "inbound_flight": "CI151",
                 "displayed_price_twd": 60000, "checked_at": stamp, "price_scope": "unknown",
                 "family_total_twd": None, "baggage_status": "unknown", "currency": "TWD"}]
        self.latest.write_text(json.dumps({"schema_version": 6, "route": CFG,
            "market_candidates": market, "itineraries": rows,
            "outbound_refresh": {f: stamp for f in ("CI154", "CX530", "JX838")}}))

    def test_full_query_builds_all_main_outbound_return_combinations(self):
        responses = [self.account(20), {"best_flights": self.items}, self.account(21)]
        for count, returns in enumerate(([flight("CI151", 61000, True), flight("CI155", 65000, True)],
                                         [flight("CX531", 81000, True)], [flight("JX839", 91000, True)]), 22):
            responses += [{"other_flights": returns}, self.account(count)]
        result, req = self.v2_run(responses, "full_query")
        self.assertEqual(result, 0)
        latest = json.loads(self.latest.read_text())
        self.assertEqual(latest["searches_used"], 4)
        self.assertTrue(latest["baseline_complete"])
        self.assertEqual({r["itinerary_key"] for r in latest["itineraries"]},
                         {"CI154+CI151", "CI154+CI155", "CX530+CX531", "JX838+JX839"})
        self.assertEqual(len(latest["market_candidates"]), 4)
        self.assertFalse(next(r for r in latest["market_candidates"] if r["outbound_flight"] == "CI150")["outbound_preference_match"])
        with (self.latest.parent / "itinerary_history.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 4)
        self.assertEqual({int(r["displayed_price_twd"]) for r in rows}, {61000, 65000, 81000, 91000})

    def test_monitor_one_scan_retains_prior_itineraries_without_new_history_prices(self):
        self.seed_v2()
        result, _ = self.v2_run([self.account(20), {"best_flights": self.items}, self.account(21)])
        self.assertEqual(result, 0)
        latest = json.loads(self.latest.read_text())
        self.assertEqual(latest["searches_used"], 1)
        self.assertEqual(latest["itineraries"][0]["displayed_price_twd"], 60000)
        self.assertFalse(latest["itineraries"][0]["observed_this_run"])
        self.assertEqual(latest["itineraries"][0]["checked_at"], (self.now - timedelta(days=1)).isoformat())
        self.assertFalse((self.latest.parent / "itinerary_history.csv").exists())

    def test_due_refresh_detects_return_price_change_with_same_market_price(self):
        self.seed_v2(age_days=4)
        responses = [self.account(20), {"best_flights": self.items}, self.account(21)]
        for usage, number, price in ((22, "CI151", 55000), (23, "CX531", 80000), (24, "JX839", 90000)):
            responses += [{"best_flights": [flight(number, price, True)]}, self.account(usage)]
        result, _ = self.v2_run(responses)
        self.assertEqual(result, 0)
        latest = json.loads(self.latest.read_text())
        self.assertEqual(latest["searches_used"], 4)
        ci = next(r for r in latest["itineraries"] if r["itinerary_key"] == "CI154+CI151")
        self.assertEqual(ci["displayed_price_twd"], 55000)
        self.assertIn("price_drop", ci["price_changes"])
        self.assertEqual(ci["previous_displayed_price_twd"], 60000)
        self.assertTrue(latest["baseline_complete"])

    def test_partial_full_query_and_reduced_refresh_do_not_claim_complete(self):
        for mode in ("full_query", "monitor_query"):
            with self.subTest(mode=mode):
                self.seed_v2(age_days=5)
                responses = [self.account(200), {"best_flights": self.items}, self.account(201),
                             {"best_flights": [flight("CI151", 55000, True)]}, self.account(202)]
                result, _ = self.v2_run(responses, mode)
                self.assertEqual(result, 0)
                latest = json.loads(self.latest.read_text())
                self.assertEqual(latest["searches_used"], 2)
                self.assertEqual(latest["refreshed_outbounds"], ["CI154"])
                self.assertEqual(set(latest["deferred_outbounds"]), {"CX530", "JX838"})
                self.assertFalse(latest["refresh_complete"])

    def test_market_only_defers_overdue_refresh_and_preserves_prior_quotes(self):
        self.seed_v2(age_days=8)
        result, _ = self.v2_run([self.account(225), {"best_flights": self.items}, self.account(226)])
        self.assertEqual(result, 0)
        latest = json.loads(self.latest.read_text())
        self.assertEqual(latest["searches_used"], 1)
        self.assertEqual(len(latest["itineraries"]), 1)
        self.assertEqual(set(latest["deferred_outbounds"]), {"CI154", "CX530", "JX838"})

    def test_late_full_query_failure_preserves_all_histories(self):
        self.seed_v2()
        history = self.latest.parent / "itinerary_history.csv"
        history.write_text("itinerary_key,displayed_price_twd\nCI154+CI151,60000\n")
        before = self.latest.read_bytes(), history.read_bytes()
        result, _ = self.v2_run([self.account(20), {"best_flights": self.items}, self.account(21),
                               {"best_flights": [flight("CI151", 55000, True)]}, self.account(22),
                               RuntimeError("secret-token")], "full_query")
        self.assertEqual(result, 2)
        self.assertEqual(before, (self.latest.read_bytes(), history.read_bytes()))
        self.assertNotIn("secret-token", (self.latest.parent / "last-run.json").read_text())

    def test_history_low_is_itinerary_price_not_market_price(self):
        self.seed_v2(age_days=4)
        history = self.latest.parent / "itinerary_history.csv"
        history.write_text("itinerary_key,displayed_price_twd,price_scope,currency,route_key,status\nCI154+CI151,52000,unknown,TWD," + m.route_key(CFG) + ",observed\n")
        responses = [self.account(200), {"best_flights": self.items}, self.account(201)]
        # Reduced tier refreshes after five days, so force an explicit full query.
        responses += [{"best_flights": [flight("CI151", 55000, True)]}, self.account(202)]
        result, _ = self.v2_run(responses, "full_query")
        self.assertEqual(result, 0)
        ci = json.loads(self.latest.read_text())["itineraries"][0]
        self.assertEqual(ci["historical_low_twd"], 52000)
        self.assertNotIn("new_low", ci["price_changes"])
        self.assertEqual(ci["previous_displayed_price_twd"], 52000)
        self.assertIn("price_increase", ci["price_changes"])

    def test_unverified_baggage_stays_unknown(self):
        item = flight("CI154")
        item["extensions"] = ["Checked baggage for a fee"]
        self.assertEqual(m.candidate(item, CFG)["baggage_status"], "unknown")

    def test_deferred_new_flight_is_not_lost_when_next_market_is_unchanged(self):
        self.seed_v2()
        items = self.items + [flight("CI152", 40000), flight("CI156", 45000)]
        result, _ = self.v2_run([self.account(20), {"best_flights": items}, self.account(21),
                                {"best_flights": [flight("CI151", 42000, True)]}, self.account(22)])
        self.assertEqual(result, 0)
        result, _ = self.v2_run([self.account(22), {"best_flights": items}, self.account(23),
                                {"best_flights": [flight("CI151", 47000, True)]}, self.account(24)])
        self.assertEqual(result, 0)
        latest = json.loads(self.latest.read_text())
        self.assertEqual(latest["searches_used"], 2)
        self.assertEqual(latest["refreshed_outbounds"], ["CI156"])

    def test_full_stops_expanding_when_live_usage_crosses_225(self):
        responses = [self.account(190), {"best_flights": self.items}, self.account(191),
                     {"best_flights": [flight("CI151", 61000, True)]}, self.account(225)]
        result, _ = self.v2_run(responses, "full_query")
        self.assertEqual(result, 0)
        latest = json.loads(self.latest.read_text())
        self.assertEqual(latest["searches_used"], 2)
        self.assertFalse(latest["refresh_complete"])
        self.assertEqual(set(latest["deferred_outbounds"]), {"CX530", "JX838"})

    def test_missing_required_token_never_claims_full_baseline(self):
        items = json.loads(json.dumps(self.items))
        del items[2]["departure_token"]
        result, _ = self.v2_run([self.account(20), {"best_flights": items}, self.account(21),
                                {"best_flights": [flight("CI151", 61000, True)]}, self.account(22),
                                {"best_flights": [flight("CX531", 80000, True)]}, self.account(23)], "full_query")
        self.assertEqual(result, 0)
        latest = json.loads(self.latest.read_text())
        self.assertFalse(latest["baseline_complete"])
        self.assertEqual(latest["missing_required_outbounds"], ["JX838"])

    def test_unreturned_combination_is_recorded_without_fabricated_zero_price(self):
        self.seed_v2(age_days=5)
        result, _ = self.v2_run([self.account(200), {"best_flights": self.items}, self.account(201),
                                {"best_flights": []}, self.account(202)], "full_query")
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(self.latest.read_text())["itineraries"], [])
        with (self.latest.parent / "itinerary_history.csv").open(newline="") as f:
            row = next(csv.DictReader(f))
        self.assertEqual(row["status"], "not_returned")
        self.assertEqual(row["displayed_price_twd"], "")
