import copy
import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("monitor", ROOT / "scripts/nagoya_flight_monitor.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
CFG = json.loads(m.CONFIG.read_text())


def offer(code="CI", price=60000, time="07:30", inbound=False):
    date = CFG["inbound_date"] if inbound else CFG["outbound_date"]
    return {"price": price, "departure_token": "test-token", "flights": [{
        "airline": code, "flight_number": code + " 154", "travel_class": "Economy",
        "departure_airport": {"id": "NGO" if inbound else "TPE", "time": date + " " + time},
        "arrival_airport": {"id": "TPE" if inbound else "NGO", "time": date + " 22:00"}}]}


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.latest = Path(self.temp.name) / "latest.json"
        self.history = Path(self.temp.name) / "history.csv"
        for target, value in (("LATEST", self.latest), ("HISTORY", self.history)):
            p = patch.object(m, target, value)
            p.start()
            self.addCleanup(p.stop)

    def account(self, used):
        return {"this_month_usage": used, "total_searches_left": 250 - used}

    def seed(self, items):
        self.latest.write_text(json.dumps({"market_candidates": [m.candidate(i, CFG) for i in items]}))

    def run_monitor(self, responses):
        with patch.dict(m.os.environ, {"SERPAPI_KEY": "fake-secret"}), patch.object(m, "request_json", side_effect=responses) as req:
            result = m.main()
        return result, req

    def test_one_scan_keeps_ci_cx_jx_and_no_time_api_filters(self):
        items = [offer("CI"), offer("CX"), offer("JX", time="15:00")]
        self.seed(items)
        result, req = self.run_monitor([self.account(100), {"best_flights": items}, self.account(101)])
        self.assertEqual(result, 0)
        data = json.loads(self.latest.read_text())
        self.assertEqual({r["airline_iata"] for r in data["market_candidates"]}, {"CI", "CX", "JX"})
        self.assertFalse(data["market_candidates"][2]["outbound_preference_match"])
        self.assertFalse(data["market_candidates"][2]["time_preference_match"])
        self.assertIsNone(data["market_candidates"][2]["inbound_preference_match"])
        self.assertEqual(data["searches_used"], 1)
        params = req.call_args_list[1].args[0]
        self.assertNotIn("outbound_times", params)
        self.assertNotIn("return_times", params)
        self.assertEqual(params["travel_class"], 1)

    def test_drop_deep_uses_token_and_keeps_return_mismatch(self):
        self.seed([offer(price=60000)])
        result, req = self.run_monitor([self.account(100), {"other_flights": [offer(price=56000)]}, self.account(101), {"best_flights": [offer("JX", price=56000, inbound=True)]}, self.account(102)])
        self.assertEqual(result, 0)
        data = json.loads(self.latest.read_text())
        self.assertEqual(data["searches_used"], 2)
        self.assertFalse(data["options"][0]["time_preference_match"])
        self.assertIsNone(data["options"][0]["family_total_twd"])
        self.assertEqual(req.call_args_list[3].args[0]["departure_token"], "test-token")

    def test_quota_boundaries_and_delayed_counters(self):
        for start, count in ((199, 1), (200, 1), (224, 1), (225, 1), (239, 1), (240, 0)):
            with self.subTest(start=start):
                self.seed([offer()])
                responses = [self.account(start)]
                if count:
                    responses += [{"best_flights": [offer("JX")]}, self.account(start)]
                result, req = self.run_monitor(responses)
                self.assertEqual(result, 0)
                run = json.loads((self.latest.parent / "last-run.json").read_text())
                self.assertEqual(run["searches_used"], count)

    def test_reduced_budget_allows_substantial_drop(self):
        self.seed([offer()])
        result, _ = self.run_monitor([self.account(200), {"best_flights": [offer(price=50000)]}, self.account(201), {"best_flights": []}, self.account(202)])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(self.latest.read_text())["searches_used"], 2)

    def test_unknown_family_price_does_not_trigger_target(self):
        row = m.candidate(offer(price=50000), CFG)
        self.assertNotIn("near_family_target", m.deep_reasons(row, [row], {}, CFG))
        row.update(price_scope="family_total", family_total_twd=50000)
        self.assertIn("near_family_target", m.deep_reasons(row, [row], {}, CFG))

    def test_api_and_parse_failures_preserve_files_and_redact_secret(self):
        missing_airport = offer()
        del missing_airport["flights"][0]["departure_airport"]["id"]
        for failure in (RuntimeError("https://example/?api_key=fake-secret"), {}, {"best_flights": "bad"}, {"best_flights": [{"flights": None}]}, {"best_flights": [missing_airport]}):
            with self.subTest(failure=failure):
                self.seed([offer()])
                self.history.write_text("custom_column\noriginal\n")
                before = self.latest.read_bytes(), self.history.read_bytes()
                result, _ = self.run_monitor([self.account(100), failure])
                self.assertEqual(result, 2)
                self.assertEqual(before, (self.latest.read_bytes(), self.history.read_bytes()))
                self.assertNotIn("fake-secret", (self.latest.parent / "last-run.json").read_text())

    def test_deep_failure_and_account_failure_preserve_snapshot(self):
        self.seed([offer()])
        before = self.latest.read_bytes()
        result, _ = self.run_monitor([self.account(100), {"best_flights": [offer("JX")]}, self.account(101), RuntimeError("blocked")])
        self.assertEqual(result, 2)
        self.assertEqual(before, self.latest.read_bytes())
        result, req = self.run_monitor([{}])
        self.assertEqual(result, 2)
        self.assertEqual(req.call_count, 1)

    def test_history_retains_unknown_columns_and_observations(self):
        self.seed([offer()])
        self.history.write_text("custom_column,displayed_price_twd\noriginal,123\n")
        result, _ = self.run_monitor([self.account(225), {"best_flights": [offer()]}, self.account(226)])
        self.assertEqual(result, 0)
        with self.history.open(newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["custom_column"], "original")
        self.assertEqual(rows[1]["record_type"], "market")
        self.assertEqual(rows[1]["searches_used"], "1")

    def test_hard_filters_and_preference_boundaries(self):
        self.assertFalse(m.candidate(offer(time="12:00"), CFG)["outbound_preference_match"])
        self.assertIsNone(m.candidate(offer("IT"), CFG))
        item = offer(); item["flights"][0]["departure_airport"]["id"] = "KHH"
        self.assertIsNone(m.candidate(item, CFG))
        item = offer(); item["flights"][0]["travel_class"] = "Business"
        self.assertIsNone(m.candidate(item, CFG))
        self.assertFalse(m.preference("2027-07-18 21:00", "21:00"))

    def test_initial_baseline_and_empty_results(self):
        result, _ = self.run_monitor([self.account(100), {"best_flights": [offer()]}, self.account(101), {"other_flights": []}, self.account(102)])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(self.latest.read_text())["market_candidates"][0]["deep_search_triggers"], ["initial_baseline"])
        result, _ = self.run_monitor([self.account(100), {"best_flights": []}, self.account(101)])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(self.latest.read_text())["status"], "no_matching_offers")

    def test_new_low_and_new_airline_triggers(self):
        row = m.candidate(offer(price=59999), CFG)
        self.assertIn("new_low", m.deep_reasons(row, [m.candidate(offer(), CFG)], {row["outbound_flight"]: 60000}, CFG))
        row = m.candidate(offer("JX"), CFG)
        self.assertIn("new_airline", m.deep_reasons(row, [m.candidate(offer(), CFG)], {}, CFG))


if __name__ == "__main__":
    unittest.main()
