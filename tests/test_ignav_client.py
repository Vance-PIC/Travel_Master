from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import ignav_client
from ignav_client import IgnavClient, IgnavError, get_ignav_key


class IgnavClientTests(unittest.TestCase):

    def test_get_ignav_key_from_env_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("Ignav_KEY=test_key_from_env_file\n", encoding="utf-8")
            
            with patch.object(ignav_client, "ENV_FILE", env_file):
                with patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(get_ignav_key(), "test_key_from_env_file")

    def test_get_ignav_key_from_os_env(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            with patch.object(ignav_client, "ENV_FILE", env_file):
                with patch.dict(os.environ, {"Ignav_KEY": "test_key_from_os_env"}):
                    self.assertEqual(get_ignav_key(), "test_key_from_os_env")

    def test_ignav_client_requires_key(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            with patch.object(ignav_client, "ENV_FILE", env_file):
                with patch.dict(os.environ, {}, clear=True):
                    client = IgnavClient(api_key=None)
                    with self.assertRaises(IgnavError) as ctx:
                        client.search_round_trip("TPE", "NGO", "2027-07-11", "2027-07-18")
                    self.assertIn("Ignav API Key is not configured", str(ctx.exception))

    def test_ignav_client_search_round_trip(self):
        client = IgnavClient(api_key="test_api_key")
        mock_resp_data = {
            "search_id": "test_search_123",
            "fares": [
                {
                    "ignav_id": "ignav_offer_001",
                    "airline": "CI",
                    "price": 68466,
                    "currency": "TWD",
                    "outbound": {"flight_number": "CI154", "departure": "07:30"},
                    "inbound": {"flight_number": "CI155", "departure": "12:15"}
                }
            ]
        }

        def mock_urlopen(req, timeout=30):
            self.assertEqual(req.get_header("X-api-key"), "test_api_key")
            self.assertEqual(req.get_method(), "POST")
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(body["origin"], "TPE")
            self.assertEqual(body["destination"], "NGO")

            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.__exit__.return_value = False
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            result = client.search_round_trip(
                origin="TPE",
                destination="NGO",
                departure_date="2027-07-11",
                return_date="2027-07-18",
                adults=2,
                children=2,
                currency="TWD",
            )
            self.assertEqual(result["search_id"], "test_search_123")
            self.assertEqual(len(result["fares"]), 1)
            self.assertEqual(result["fares"][0]["ignav_id"], "ignav_offer_001")

    def test_ignav_client_get_booking_links(self):
        client = IgnavClient(api_key="test_api_key")
        mock_resp_data = {
            "ignav_id": "ignav_offer_001",
            "booking_options": [
                {
                    "provider": "China Airlines Direct",
                    "url": "https://www.china-airlines.com/booking?ref=ignav",
                    "price": 68466,
                    "currency": "TWD"
                },
                {
                    "provider": "Trip.com",
                    "url": "https://tw.trip.com/flights?ref=ignav",
                    "price": 67742,
                    "currency": "TWD"
                }
            ]
        }

        def mock_urlopen(req, timeout=30):
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.__exit__.return_value = False
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            result = client.get_booking_links("ignav_offer_001")
            self.assertEqual(result["ignav_id"], "ignav_offer_001")
            self.assertEqual(len(result["booking_options"]), 2)
            self.assertIn("Trip.com", result["booking_options"][1]["provider"])

    def test_ignav_client_search_airports(self):
        client = IgnavClient(api_key=None)
        mock_resp_data = [
            {"iata": "TPE", "name": "Taiwan Taoyuan International Airport", "city": "Taipei"},
            {"iata": "NGO", "name": "Chubu Centrair International Airport", "city": "Nagoya"}
        ]

        def mock_urlopen(req, timeout=30):
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_resp.__exit__.return_value = False
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            result = client.search_airports("Taipei")
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["iata"], "TPE")


if __name__ == "__main__":
    unittest.main()
