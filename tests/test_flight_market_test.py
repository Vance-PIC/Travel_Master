import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class MarketExperimentTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "scripts/flight_market_test.py"
        self.assertTrue(path.exists(), "Independent Market Scan test entry point is missing")
        with patch.object(sys, "path", [str(ROOT / "scripts")] + sys.path):
            spec = importlib.util.spec_from_file_location("market_test", path)
            self.experiment = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.experiment)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "flights"
        self.data.mkdir()
        for name in ("latest.json", "history.csv", "itinerary_history.csv", "last-run.json"):
            (self.data / name).write_text("original " + name, encoding="utf-8")
        self.original = {p.name: p.read_bytes() for p in self.data.iterdir()}
        patcher = patch.object(self.experiment.monitor, "LATEST", self.data / "latest.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.output = self.data / "experiments"
        self.requests = []

    def account(self, usage):
        return {"this_month_usage": usage, "total_searches_left": 250 - usage}

    def offer(self, number, price):
        return {"price": price, "departure_token": "secret-token", "flights": [{
            "flight_number": number, "airline": number[:2], "travel_class": "Economy",
            "departure_airport": {"id": "TPE", "time": "2027-07-11 14:55"},
            "arrival_airport": {"id": "NGO", "time": "2027-07-11 18:45"}}]}

    def fake_request(self, params, endpoint=None, timeout=45):
        self.requests.append((dict(params), endpoint, timeout))
        if endpoint == self.experiment.monitor.ACCOUNT_BASE:
            count = sum(r[1] != endpoint for r in self.requests)
            return self.account(20 + count)
        if params["deep_search"] == "true":
            return {"best_flights": [self.offer("CI154", 60000), self.offer("JX838", 80000)]}
        return {"best_flights": [self.offer("CI154", 63000)]}

    def execute(self, **kwargs):
        with patch.dict(self.experiment.os.environ, {"SERPAPI_KEY": "fake-secret"}), patch.object(
                self.experiment.monitor, "request_json", side_effect=self.fake_request):
            return self.experiment.run(output_dir=self.output, **kwargs)

    def assert_protected(self):
        self.assertEqual(self.original, {name: (self.data / name).read_bytes() for name in self.original})

    def test_single_true_and_false_each_do_one_market_request(self):
        for enabled, expected_count in ((False, 1), (True, 2)):
            with self.subTest(enabled=enabled):
                self.requests = []
                result = self.execute(deep_search=enabled)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["searches_used"], 1)
                self.assertEqual(result["account_calls"], 2)
                row = result["results"][0]
                self.assertEqual(row["deep_search"], enabled)
                self.assertEqual(row["flight_count"], expected_count)
                self.assertGreaterEqual(row["response_time_seconds"], 0)
                self.assertEqual(row["quota_before"]["usage"], 20)
                self.assertEqual(row["quota_after"]["usage"], 21)
                self.assert_protected()

    def test_comparison_differs_only_in_deep_search_and_retains_prices(self):
        result = self.execute(compare=True)
        scans = [r[0] for r in self.requests if r[1] != self.experiment.monitor.ACCOUNT_BASE]
        self.assertEqual(len(scans), 2)
        self.assertNotIn("departure_token", scans[0])
        self.assertNotIn("departure_token", scans[1])
        self.assertNotIn("outbound_times", scans[0])
        self.assertNotIn("return_times", scans[0])
        self.assertEqual(scans[0].pop("deep_search"), "false")
        self.assertEqual(scans[1].pop("deep_search"), "true")
        self.assertEqual(scans[0], scans[1])
        self.assertEqual(result["searches_used"], 2)
        self.assertEqual(result["account_calls"], 4)
        self.assertEqual(result["comparison"]["added_flights"], ["JX838"])
        self.assertEqual(result["comparison"]["price_differences"][0]["difference_twd"], -3000)
        self.assertEqual(result["results"][1]["flights"][1]["price_scope"], "unknown")
        text = (Path(result["output_path"])).read_text(encoding="utf-8")
        self.assertNotIn("fake-secret", text)
        self.assertNotIn("secret-token", text)
        self.assert_protected()

    def test_api_failure_writes_only_sanitized_experiment_error(self):
        with patch.dict(self.experiment.os.environ, {"SERPAPI_KEY": "fake-secret"}), patch.object(
                self.experiment.monitor, "request_json", side_effect=[self.account(20), RuntimeError("fake-secret"), self.account(21)]):
            result = self.experiment.run(compare=True, output_dir=self.output)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["searches_used"], 1)
        self.assertEqual(result["results"][0]["quota_after"]["usage"], 21)
        self.assertNotIn("fake-secret", json.dumps(result))
        self.assert_protected()

    def test_quota_239_stops_second_variant_even_if_counters_lag(self):
        with patch.dict(self.experiment.os.environ, {"SERPAPI_KEY": "fake-secret"}), patch.object(
                self.experiment.monitor, "request_json", side_effect=[self.account(239), {"best_flights": []}, self.account(239), self.account(239)]):
            result = self.experiment.run(compare=True, output_dir=self.output)
        self.assertEqual(result["searches_used"], 1)
        self.assertEqual(result["status"], "quota_limited")
        self.assertEqual(result["results"][1]["status"], "quota_preserved")
        self.assert_protected()

    def test_rejects_output_in_production_data_directory(self):
        with self.assertRaises(ValueError):
            self.experiment.run(output_dir=self.data)
        self.assert_protected()
