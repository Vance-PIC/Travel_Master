import base64
import csv
import importlib.util
import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

try:
    SDK_AVAILABLE = importlib.util.find_spec("mcp.server.fastmcp") is not None
except (ImportError, ModuleNotFoundError):
    SDK_AVAILABLE = False


class HotelStoreDispatchTests(unittest.TestCase):
    def test_dispatch_hotel_monitor_success(self):
        import github_store

        requests = []

        class DummyResponse(io.BytesIO):
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

        def mock_urlopen(req, timeout=20):
            requests.append(req)
            return DummyResponse(b"")

        with patch.dict(os.environ, {"GITHUB_TOKEN": "token-xyz", "GITHUB_REPO": "Vance-PIC/Travel_Master"}), \
                patch.object(github_store.urllib.request, "urlopen", side_effect=mock_urlopen):
            res = github_store.dispatch_hotel_monitor("marunouchi-booked", '{"mode":"test"}')

        self.assertEqual(res["status"], "queued")
        self.assertIn("hotel-monitor.yml", res["workflow_url"])
        self.assertEqual(len(requests), 1)
        self.assertTrue(requests[0].full_url.endswith("/dispatches"))
        data = json.loads(requests[0].data.decode("utf-8"))
        self.assertEqual(data["inputs"]["monitor"], "marunouchi-booked")
        self.assertEqual(data["inputs"]["request_json"], '{"mode":"test"}')

    def test_dispatch_hotel_monitor_invalid_id_or_json(self):
        import github_store

        with patch.dict(os.environ, {"GITHUB_TOKEN": "token-xyz", "GITHUB_REPO": "Vance-PIC/Travel_Master"}):
            with self.assertRaises(github_store.GitHubStoreError):
                github_store.dispatch_hotel_monitor("invalid/id!@#")

            with self.assertRaises(github_store.GitHubStoreError):
                github_store.dispatch_hotel_monitor("airport-candidate", "invalid-json-string{")


@unittest.skipUnless(SDK_AVAILABLE, "Install mcp/requirements.txt for MCP tests")
class HotelServerUnitTests(unittest.TestCase):
    def test_hotel_search_missing_key(self):
        import hotel_server

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SEARCHAPI_KEY is not configured"):
                hotel_server.hotel_search(
                    q="Nagoya",
                    check_in_date="2027-07-17",
                    check_out_date="2027-07-18",
                )

    def test_hotel_search_api_error_does_not_leak_key(self):
        import hotel_server

        secret = "secret-searchapi-key-999"
        with patch.dict(os.environ, {"SEARCHAPI_KEY": secret}), \
                patch.object(hotel_server.urllib.request, "urlopen",
                             side_effect=urllib.error.URLError("http://example.com?api_key=" + secret)):
            with self.assertRaises(RuntimeError) as ctx:
                hotel_server.hotel_search(
                    q="Nagoya",
                    check_in_date="2027-07-17",
                    check_out_date="2027-07-18",
                )
        self.assertNotIn(secret, str(ctx.exception))

    def test_hotel_search_success_and_filtering(self):
        import hotel_server

        mock_payload = {
            "properties": [
                {
                    "name": "Hotel A",
                    "extracted_hotel_class": 3,
                    "overall_rating": 4.5,
                    "total_rate": {"extracted_price": 5000, "lowest": "NT$5,000"},
                    "rate_per_night": {"extracted_price": 2500, "lowest": "NT$2,500"},
                    "reviews": 100,
                    "amenities": ["Wi-Fi", "Non-smoking"],
                    "data_id": "hotel_a",
                },
                {
                    "name": "Hotel B",
                    "extracted_hotel_class": 4,
                    "overall_rating": 3.8,
                    "total_rate": {"extracted_price": 3000, "lowest": "NT$3,000"},
                    "rate_per_night": {"extracted_price": 1500, "lowest": "NT$1,500"},
                    "reviews": 50,
                    "amenities": ["Wi-Fi"],
                    "data_id": "hotel_b",
                },
            ]
        }

        class MockResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

        with patch.dict(os.environ, {"SEARCHAPI_KEY": "valid-key"}), \
                patch.object(hotel_server.urllib.request, "urlopen",
                             side_effect=lambda *args, **kwargs: MockResponse(json.dumps(mock_payload).encode())):
            # Test filter rating >= 4.0 (should only return Hotel A)
            res = hotel_server.hotel_search(
                q="Nagoya",
                check_in_date="2027-07-17",
                check_out_date="2027-07-18",
                rating=4.0,
            )
            self.assertEqual(len(res["results"]), 1)
            self.assertEqual(res["results"][0]["name"], "Hotel A")
            self.assertEqual(res["results"][0]["price"], 5000)

            # Test sort ascending by price without rating filter
            res_all = hotel_server.hotel_search(
                q="Nagoya",
                check_in_date="2027-07-17",
                check_out_date="2027-07-18",
            )
            self.assertEqual(len(res_all["results"]), 2)
            self.assertEqual(res_all["results"][0]["name"], "Hotel B")
            self.assertEqual(res_all["results"][1]["name"], "Hotel A")

    def test_hotel_monitor_unsupported(self):
        import hotel_server

        res1 = hotel_server.hotel_monitor(action="status", trip_id="osaka")
        self.assertEqual(res1["status"], "unsupported_trip")

        res2 = hotel_server.hotel_monitor(action="status", trip_id="nagoya", monitor_id="invalid-id")  # type: ignore
        self.assertEqual(res2["status"], "unsupported_monitor")

    def test_hotel_monitor_remote_status_and_run(self):
        import hotel_server
        import github_store

        files = {
            "travel/nagoya/hotel-monitor.json": b'{"monitors":[{"monitor_id":"marunouchi-booked","stage":"booked_room_compare"}]}',
            "travel/nagoya/hotels/marunouchi-booked/last-run.json": b'{"status":"ok","timestamp":"2026-10-05T00:00:00Z"}',
            "travel/nagoya/hotels/marunouchi-booked/latest.json": b'{"checked_at":"2026-10-05T00:00:00Z","status":"stored_snapshot"}',
        }

        with patch.dict(os.environ, {"HOTEL_MCP_REMOTE": "1"}), \
                patch.object(github_store, "get_file", side_effect=files.__getitem__):
            status = hotel_server.hotel_monitor(action="status", trip_id="nagoya", monitor_id="marunouchi-booked")
            self.assertEqual(status["trip_id"], "nagoya")
            self.assertEqual(status["monitor_id"], "marunouchi-booked")
            self.assertEqual(status["latest_status"], "stored_snapshot")
            self.assertEqual(status["config"]["stage"], "booked_room_compare")

        with patch.dict(os.environ, {"HOTEL_MCP_REMOTE": "1"}), \
                patch.object(github_store, "dispatch_hotel_monitor",
                             return_value={"status": "queued", "workflow_url": "https://github.com/workflows/1"}) as mock_dispatch:
            run_res = hotel_server.hotel_monitor(action="run", trip_id="nagoya", monitor_id="marunouchi-booked")
            mock_dispatch.assert_called_once_with("marunouchi-booked", None)
            self.assertEqual(run_res["status"], "queued")

    def test_hotel_report_remote_current_and_history(self):
        import hotel_server
        import github_store

        latest_json = {
            "checked_at": "2026-10-05T00:00:00Z",
            "status": "stored_snapshot",
            "stage": "booked_room_compare",
            "stay": {"check_in": "2027-07-17", "check_out": "2027-07-23"},
            "party": {"adults": 2, "children": 2},
            "summary": {"best_match": "Standard Twin Non-Smoking"},
        }
        history_csv = b"run_id,monitor_id,observed_at,status,amount\nrun-1,marunouchi-booked,2026-10-04,pass,12000\nrun-2,marunouchi-booked,2026-10-05,pass,11500\n"

        files = {
            "travel/nagoya/hotels/marunouchi-booked/latest.json": json.dumps(latest_json).encode(),
            "travel/nagoya/hotels/marunouchi-booked/history.csv": history_csv,
        }

        with patch.dict(os.environ, {"HOTEL_MCP_REMOTE": "1"}), \
                patch.object(github_store, "get_file", side_effect=files.__getitem__):
            curr = hotel_server.hotel_report("current", trip_id="nagoya", monitor_id="marunouchi-booked")
            self.assertEqual(curr["status"], "stored_snapshot")
            self.assertEqual(curr["summary"]["best_match"], "Standard Twin Non-Smoking")

            hist = hotel_server.hotel_report("history", trip_id="nagoya", monitor_id="marunouchi-booked", limit=1)
            self.assertEqual(len(hist["history"]), 1)
            self.assertEqual(hist["history"][0]["run_id"], "run-2")


if __name__ == "__main__":
    unittest.main()
