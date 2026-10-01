import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class PriceScopeTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "scripts/price_scope_experiment.py"
        self.assertTrue(path.exists(), "Isolated price-scope experiment entry point is missing")
        with patch.object(sys, "path", [str(ROOT / "scripts")] + sys.path):
            spec = importlib.util.spec_from_file_location("price_scope", path)
            self.exp = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.exp)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.before = {}
        for name in ("latest.json", "history.csv", "itinerary_history.csv", "last-run.json"):
            (self.root / name).write_text("original", encoding="utf-8")
            self.before[name] = (self.root / name).read_bytes()
        p = patch.object(self.exp.monitor, "LATEST", self.root / "latest.json")
        p.start()
        self.addCleanup(p.stop)
        self.calls = []

    def payload(self, price):
        return {"selected_flights": [{"flights": [{"flight_number": "CI 154", "travel_class": "Economy",
            "departure_airport": {"id": "TPE", "time": "2027-07-11 07:30"},
            "arrival_airport": {"id": "NGO", "time": "2027-07-11 11:20"}}], "booking_token": "sensitive-token"},
            {"flights": [{"flight_number": "CI 151", "travel_class": "Economy",
            "departure_airport": {"id": "NGO", "time": "2027-07-18 09:55"},
            "arrival_airport": {"id": "TPE", "time": "2027-07-18 11:55"}}]}],
            "booking_options": [{"together": {"book_with": "China Airlines", "price": price,
            "local_prices": [{"currency": "TWD", "price": price}], "option_title": "Economy",
            "extensions": ["No refunds"], "baggage_prices": ["1 checked bag"],
            "booking_request": {"url": "secret-url"}}}], "baggage_prices": {"together": ["1 checked bag"]}}

    def request(self, params, endpoint=None, timeout=45):
        self.calls.append((dict(params), endpoint))
        if endpoint == self.exp.monitor.ACCOUNT_BASE:
            used = 20 + sum(e != endpoint for _, e in self.calls)
            return {"this_month_usage": used, "total_searches_left": 250 - used}
        return self.payload(15000 if params["adults"] == 1 else 57000)

    def test_two_pinned_searches_differ_only_in_passengers_and_preserve_state(self):
        with patch.dict(self.exp.os.environ, {"SERPAPI_KEY": "fake-secret"}), patch.object(self.exp.monitor, "request_json", side_effect=self.request):
            result = self.exp.run()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["searches_used"], 2)
        self.assertEqual(result["account_calls"], 4)
        scans = [p for p, e in self.calls if e != self.exp.monitor.ACCOUNT_BASE]
        self.assertEqual([(p.pop("adults"), p.pop("children")) for p in scans], [(1, 0), (2, 2)])
        self.assertEqual(scans[0], scans[1])
        self.assertNotIn("booking_token", scans[0])
        self.assertNotIn("departure_token", scans[0])
        pinned = json.loads(scans[0]["selected_flights_json"])
        self.assertEqual(pinned["outbound"][0]["flight_number"], "CI154")
        self.assertEqual(pinned["return"][0]["flight_number"], "CI151")
        self.assertEqual(result["comparison"]["matched_options"][0]["b_over_a"], 3.8)
        self.assertEqual(result["results"][0]["booking_options"][0]["together"]["local_prices"][0]["price"], 15000)
        self.assertEqual(self.before, {n: (self.root / n).read_bytes() for n in self.before})
        text = Path(result["output_path"]).read_text(encoding="utf-8")
        for secret in ("fake-secret", "sensitive-token", "secret-url"):
            self.assertNotIn(secret, text)

    def test_different_fare_or_duplicate_seller_options_are_not_false_matches(self):
        a, b = self.payload(15000), self.payload(57000)
        b["booking_options"][0]["together"]["option_title"] = "Flexible"
        result = self.exp.compare_options(a["booking_options"], b["booking_options"])
        self.assertEqual(result["matched_options"], [])
        b = self.payload(57000)
        b["booking_options"] *= 2
        self.assertEqual(self.exp.compare_options(a["booking_options"], b["booking_options"])["matched_options"], [])

    def test_failure_stops_without_retry_and_preserves_all_production_files(self):
        account = {"this_month_usage": 20, "total_searches_left": 230}
        with patch.dict(self.exp.os.environ, {"SERPAPI_KEY": "fake-secret"}), patch.object(self.exp.monitor, "request_json", side_effect=[account, RuntimeError("fake-secret"), account]):
            result = self.exp.run()
        self.assertEqual(result["searches_used"], 1)
        self.assertEqual(result["status"], "error")
        self.assertNotIn("fake-secret", json.dumps(result))
        self.assertEqual(self.before, {n: (self.root / n).read_bytes() for n in self.before})

    def test_wrong_selected_itinerary_is_rejected(self):
        response = self.payload(15000)
        response["selected_flights"][1]["flights"][0]["flight_number"] = "CI155"
        with self.assertRaises(ValueError):
            self.exp.validate_selected(response["selected_flights"])
