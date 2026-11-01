from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.api import server
from src.db.database import (
    get_connection,
    init_db,
    insert_roundtrip_snapshot,
    upsert_flight_instance,
)
from src.db.models import FlightInstance, RoundTripSnapshot
from src.planner import service as planner_service


class PlannerServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_file = str(Path(self.tmpdir.name) / "planner_test.sqlite3")
        init_db(self.db_file)
        self.db_patch = patch("src.planner.service.db_path", return_value=self.db_file)
        self.db_patch.start()
        self.serp_key_patch = patch("src.planner.service._get_serpapi_key", return_value=None)
        self.serp_key_patch.start()

    def tearDown(self):
        self.serp_key_patch.stop()
        self.db_patch.stop()
        self.tmpdir.cleanup()

    def _sample_draft_payload(self, children=None):
        return {
            "origin": "TPE",
            "destinations": ["KIX", "KMJ"],
            "outbound_start": "2027-07-11",
            "outbound_end": "2027-07-12",
            "return_start": "2027-07-17",
            "return_end": "2027-07-18",
            "travelers": {
                "adults": 2,
                "children": children if children is not None else [{"age_at_departure": 7}, {"age_at_departure": 13}],
            },
        }

    def _sample_itinerary(self, out_date="2027-07-11", in_date="2027-07-17", amount=15800.0, ignav_id="offer-1"):
        return {
            "origin": "TPE",
            "destination": "KIX",
            "outbound_date": out_date,
            "return_date": in_date,
            "outbound": {
                "flight_number": "BR108",
                "departure_time": "07:55",
                "arrival_time": "11:35",
                "stops": 0,
                "airline": "EVA Air",
            },
            "inbound": {
                "flight_number": "BR109",
                "departure_time": "12:45",
                "arrival_time": "15:05",
                "stops": 0,
                "airline": "EVA Air",
            },
            "airline": "EVA Air",
            "amount": amount,
            "currency": "TWD",
            "price_scope": "per_person",
            "provider": "ignav",
            "ignav_id": ignav_id,
        }

    def test_draft_save_and_traveler_age_classification(self):
        draft = planner_service.save_draft(self._sample_draft_payload())
        loaded = planner_service.get_draft(draft["id"])
        self.assertIsNone(loaded["budget_twd"])
        self.assertIsNotNone(loaded)
        self.assertEqual(["KIX", "KMJ"], loaded["destinations"])
        adults, children, has_infant = planner_service._traveler_counts(loaded["travelers"])
        # 2 adults + 13yo child => 3 provider adults; 7yo child => 1 provider child
        self.assertEqual(3, adults)
        self.assertEqual(1, children)
        self.assertFalse(has_infant)

    def test_candidate_identity_distinguishes_dates_and_merges_legacy_snapshots(self):
        # Seed a legacy roundtrip snapshot in the database for 2027-07-11 BR108 / 2027-07-17 BR109
        conn = get_connection(self.db_file)
        ob_id, _ = upsert_flight_instance(conn, FlightInstance(
            flight_date="2027-07-11", trip_type="OUTBOUND",
            origin_airport="TPE", dest_airport="KIX", airline_code="BR",
            flight_number="BR108", departure_time="07:55", arrival_time="11:35", stops=0,
        ))
        ib_id, _ = upsert_flight_instance(conn, FlightInstance(
            flight_date="2027-07-17", trip_type="INBOUND",
            origin_airport="KIX", dest_airport="TPE", airline_code="BR",
            flight_number="BR109", departure_time="12:45", arrival_time="15:05", stops=0,
        ))
        insert_roundtrip_snapshot(conn, RoundTripSnapshot(
            outbound_flight_instance_id=ob_id,
            inbound_flight_instance_id=ib_id,
            window_key="W1",
            source="google_flights",
            price_twd=14200,
            passenger_count=1,
        ))
        conn.close()

        draft = planner_service.save_draft(self._sample_draft_payload())
        c1 = planner_service.add_candidate(draft["id"], self._sample_itinerary("2027-07-11", "2027-07-17", 15800.0))
        c2 = planner_service.add_candidate(draft["id"], self._sample_itinerary("2027-07-12", "2027-07-18", 16200.0))

        self.assertNotEqual(c1["id"], c2["id"])
        self.assertEqual("tracking", c1["tracking_status"])
        # c1 should have both the legacy observation (14200) and the live observation (15800)
        amounts = [o["amount"] for o in c1["observations"]]
        self.assertIn(14200.0, amounts)
        self.assertIn(15800.0, amounts)
        sources = [o["source"] for o in c1["observations"]]
        self.assertIn("history:google_flights", sources)
        # c2 (different dates, same flight numbers) should only have its own observation
        self.assertEqual([16200.0], [o["amount"] for o in c2["observations"]])

        # Historical itineraries lookup matches the draft
        hist = planner_service.historical_itineraries(draft["id"])
        self.assertEqual(1, len(hist))
        self.assertEqual(14200.0, hist[0]["amount"])
        self.assertEqual("BR108", hist[0]["outbound"]["flight_number"])

    def test_changed_draft_keeps_previous_candidates_separate_and_pauses_them(self):
        payload = self._sample_draft_payload(children=[])
        draft = planner_service.save_draft(payload)
        old = planner_service.add_candidate(
            draft["id"], self._sample_itinerary("2027-07-11", "2027-07-17")
        )
        current = planner_service.add_candidate(
            draft["id"], self._sample_itinerary("2027-07-12", "2027-07-18")
        )

        payload.update({
            "outbound_start": "2027-07-12", "outbound_end": "2027-07-12",
            "return_start": "2027-07-18", "return_end": "2027-07-18",
        })
        planner_service.save_draft(payload, draft["id"])
        candidates = {c["id"]: c for c in planner_service.list_candidates(draft["id"])}
        self.assertFalse(candidates[old["id"]]["matches_current_draft"])
        self.assertEqual("paused", candidates[old["id"]]["tracking_status"])
        self.assertTrue(candidates[current["id"]]["matches_current_draft"])
        self.assertEqual("tracking", candidates[current["id"]]["tracking_status"])

        payload["travelers"] = {"adults": 2, "children": [{"age_at_departure": 7}]}
        planner_service.save_draft(payload, draft["id"])
        candidates = {c["id"]: c for c in planner_service.list_candidates(draft["id"])}
        self.assertFalse(candidates[current["id"]]["matches_current_draft"])
        self.assertEqual("paused", candidates[current["id"]]["tracking_status"])

    def test_pause_resume_target_and_p3_decision_with_mocked_provider(self):
        draft = planner_service.save_draft(self._sample_draft_payload())
        cand = planner_service.add_candidate(draft["id"], self._sample_itinerary())
        updated = planner_service.set_candidate(cand["id"], status="paused", target_price=14500.0)
        self.assertEqual("paused", updated["tracking_status"])
        self.assertEqual(14500.0, updated["target_price"])

        mock_client = MagicMock()
        mock_client.get_booking_links.return_value = {
            "booking_options": [
                {
                    "provider": "EVA Air Official",
                    "price": {"amount": 58400, "currency": "TWD"},
                    "price_scope": "party_total",
                    "url": "https://booking.example.com/eva",
                    "terms": "含 23kg 行李",
                }
            ]
        }
        with patch("src.planner.service._client", return_value=(mock_client, Exception)):
            decision = planner_service.decide_candidate(cand["id"])
        self.assertEqual("ready", decision["status"])
        self.assertEqual(1, len(decision["booking_options"]))
        self.assertEqual(58400.0, decision["booking_options"][0]["amount"])
        self.assertEqual("https://booking.example.com/eva", decision["booking_options"][0]["url"])

        stored = planner_service.current_decision()
        self.assertIsNotNone(stored)
        self.assertEqual(cand["id"], stored["candidate_id"])

    def test_p1_budget_defaults_new_candidate_without_overwriting_p2_target(self):
        payload = self._sample_draft_payload()
        payload["budget_twd"] = 60000
        draft = planner_service.save_draft(payload)
        self.assertEqual(60000, planner_service.get_draft(draft["id"])["budget_twd"])
        first = planner_service.add_candidate(draft["id"], self._sample_itinerary())
        self.assertEqual(60000, first["target_price"])
        planner_service.set_candidate(first["id"], target_price=55000, update_target=True)
        payload["budget_twd"] = 50000
        planner_service.save_draft(payload, draft["id"])
        second = planner_service.add_candidate(draft["id"], self._sample_itinerary("2027-07-12", "2027-07-18"))
        self.assertEqual(50000, second["target_price"])
        self.assertEqual(55000, planner_service.list_candidates(draft["id"])[0]["target_price"])

    def test_existing_booking_quotes_are_migrated_for_p3_decision(self):
        draft = planner_service.save_draft(self._sample_draft_payload())
        cand = planner_service.add_candidate(draft["id"], self._sample_itinerary())
        conn = get_connection(self.db_file)
        conn.execute("DROP TABLE planner_booking_quotes")
        conn.execute(
            "CREATE TABLE planner_booking_quotes ("
            "id INTEGER PRIMARY KEY, candidate_id TEXT NOT NULL, provider TEXT NOT NULL, "
            "amount REAL, currency TEXT, price_scope TEXT NOT NULL DEFAULT 'unknown', "
            "booking_url TEXT, status TEXT NOT NULL, terms TEXT, "
            "observed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO planner_booking_quotes "
            "(candidate_id, provider, amount, currency, status) VALUES (?, ?, ?, ?, ?)",
            (cand["id"], "Legacy provider", 12000, "TWD", "available"),
        )
        conn.execute(
            "INSERT INTO planner_decisions (id, candidate_id, traveler_json) VALUES (1, ?, ?)",
            (cand["id"], json.dumps(draft, ensure_ascii=False)),
        )
        conn.commit()
        conn.close()

        init_db(self.db_file)
        init_db(self.db_file)  # Repeated startup must leave the migration safe.
        stored = planner_service.current_decision()
        self.assertEqual(cand["id"], stored["candidate_id"])
        self.assertEqual("Legacy provider", stored["booking_options"][0]["provider"])
        self.assertIsNone(stored["booking_options"][0]["passenger_fares_json"])
        self.assertEqual(0, stored["booking_options"][0]["separate_tickets"])

    def test_infant_under_two_blocks_unverified_total_quote(self):
        draft = planner_service.save_draft(self._sample_draft_payload(children=[{"age_at_departure": 1}]))
        cand = planner_service.add_candidate(draft["id"], self._sample_itinerary())
        decision = planner_service.decide_candidate(cand["id"])
        self.assertEqual("needs_infant_choice", decision["status"])

    def test_booking_preview_keeps_final_decision_unchanged(self):
        draft = planner_service.save_draft(self._sample_draft_payload())
        first = planner_service.add_candidate(draft["id"], self._sample_itinerary())
        second = planner_service.add_candidate(draft["id"], self._sample_itinerary("2027-07-12", "2027-07-18"))
        mock_client = MagicMock()
        mock_client.get_booking_links.return_value = {
            "booking_options": [{
                "provider": "EVA Air Official", "price": {"amount": 58400, "currency": "TWD"},
                "price_scope": "party_total", "url": "https://booking.example.com/eva",
            }]
        }
        with patch("src.planner.service._client", return_value=(mock_client, Exception)):
            preview = planner_service.preview_booking_candidate(first["id"])
            self.assertEqual("ready", preview["status"])
            self.assertIsNone(planner_service.current_decision())
            planner_service.decide_candidate(second["id"])
            planner_service.preview_booking_candidate(first["id"])
        self.assertEqual(second["id"], planner_service.current_decision()["candidate_id"])

    def test_root_route_serves_new_ui_and_legacy_route_serves_old_ui(self):
        root_resp = server.index()
        legacy_resp = server.legacy_dashboard()
        self.assertTrue(str(root_resp.path).endswith("trip_planner.html"))
        self.assertTrue(str(legacy_resp.path).endswith("index.html"))

    def test_chinese_airport_search_and_code_resolution(self):
        # Search by Traditional Chinese city/airport/region keywords
        tyo = planner_service.airport_search("桃園")
        self.assertEqual("TPE", tyo[0]["iata"])
        kyushu = [a["iata"] for a in planner_service.airport_search("九州")]
        self.assertIn("FUK", kyushu)
        self.assertIn("KMJ", kyushu)
        # Save draft directly with Chinese text and formatted labels
        payload = self._sample_draft_payload()
        payload["origin"] = "桃園"
        payload["destinations"] = ["名古屋", "大阪 (KIX)", "阿蘇熊本"]
        draft = planner_service.save_draft(payload)
        self.assertEqual("TPE", draft["origin"])
        self.assertEqual(["KIX", "KMJ", "NGO"], draft["destinations"])

    def test_serpapi_nagoya_monitor_integration_and_channel_comparison(self):
        status = planner_service.engine_status()
        self.assertIn("serpapi_quota", status)

        payload = self._sample_draft_payload()
        payload["destinations"] = ["NGO"]
        draft = planner_service.save_draft(payload)
        hist = planner_service.historical_itineraries(draft["id"])
        keys = [f"{i['outbound']['flight_number']}+{i['inbound']['flight_number']}" for i in hist]
        self.assertIn("CI154+CI151", keys)
        self.assertIn("CI154+CI155", keys)

        ci_item = next(i for i in hist if i["outbound"]["flight_number"] == "CI154" and i["inbound"]["flight_number"] == "CI155")
        cand = planner_service.add_candidate(draft["id"], ci_item)
        # Should include historical observations from travel/nagoya/flights/itinerary_history.csv
        self.assertGreaterEqual(len(cand["observations"]), 5)

        decision = planner_service.decide_candidate(cand["id"])
        self.assertEqual(3, len(decision["channel_comparison"]))
        self.assertIn("中華航空官網直營", decision["channel_comparison"][0]["title"])
        # No provider-specific prices are available for these generic links; do not invent estimates.
        self.assertTrue(all(option["amount"] is None for option in decision["channel_comparison"]))

    def test_engine_status_does_not_invent_quota_or_provider_health(self):
        missing = Path(self.tmpdir.name) / "does-not-exist.json"
        with (
            patch("src.planner.service._NAGOYA_LATEST_JSON", missing),
            patch("src.planner.service._NAGOYA_MONITOR_JSON", missing),
            patch("src.planner.service._get_serpapi_key", return_value=None),
            patch("src.planner.service._client", side_effect=planner_service.PlannerError("no key")),
        ):
            status = planner_service.engine_status()
        self.assertIsNone(status["serpapi_quota"]["used"])
        self.assertIsNone(status["serpapi_quota"]["remaining"])
        self.assertIsNone(status["serpapi_quota"]["total"])
        self.assertFalse(status["serpapi_active"])
        self.assertFalse(status["ignav_active"])
        self.assertIsNone(status["monitor_config"]["destination"])

    def test_dual_engine_search_merges_serpapi_and_ignav(self):
        payload = {
            "origin": "TPE",
            "destinations": ["NGO"],
            "outbound_start": "2027-07-04",
            "outbound_end": "2027-07-05",
            "return_start": "2027-07-11",
            "return_end": "2027-07-11",
            "travelers": {"adults": 2, "children": []},
        }
        draft = planner_service.save_draft(payload)

        def fake_serpapi_request(params, endpoint="", timeout=25):
            if params.get("departure_token") == "tok-ci154":
                return {
                    "best_flights": [
                        {
                            "flights": [
                                {
                                    "flight_number": "CI 155",
                                    "airline": "China Airlines",
                                    "departure_airport": {"time": "2027-07-11 12:00"},
                                    "arrival_airport": {"time": "2027-07-11 14:10"},
                                }
                            ],
                            "price": 32600,
                        }
                    ]
                }
            if params.get("departure_token") == "tok-it206":
                return {
                    "best_flights": [
                        {
                            "flights": [
                                {
                                    "flight_number": "IT 207",
                                    "airline": "Tigerair Taiwan",
                                    "departure_airport": {"time": "2027-07-11 13:45"},
                                    "arrival_airport": {"time": "2027-07-11 15:50"},
                                }
                            ],
                            "price": 23800,
                        }
                    ]
                }
            return {
                "best_flights": [
                    {
                        "flights": [
                            {
                                "flight_number": "CI 154",
                                "airline": "China Airlines",
                                "departure_airport": {"time": f"{params['outbound_date']} 07:35"},
                                "arrival_airport": {"time": f"{params['outbound_date']} 11:25"},
                            }
                        ],
                        "price": 32600,
                        "departure_token": "tok-ci154",
                    }
                ],
                "other_flights": [
                    {
                        "flights": [
                            {
                                "flight_number": "IT 206",
                                "airline": "Tigerair Taiwan",
                                "departure_airport": {"time": f"{params['outbound_date']} 09:00"},
                                "arrival_airport": {"time": f"{params['outbound_date']} 12:55"},
                            }
                        ],
                        "price": 23800,
                        "departure_token": "tok-it206",
                    }
                ],
            }

        mock_client = MagicMock()
        mock_client.search_round_trip.return_value = {
            "itineraries": [
                {
                    "ignav_id": "ignav-it206-207",
                    "price": 752,
                    "currency": "USD",
                    "bags": {"checked": 1, "carry_on": 1},
                    "outbound": {
                        "carrier_code": "IT",
                        "flight_number": "206",
                        "departure_time": "2027-07-04T09:00:00",
                        "arrival_time": "2027-07-04T12:55:00",
                        "stops": 0,
                    },
                    "inbound": {
                        "carrier_code": "IT",
                        "flight_number": "207",
                        "departure_time": "2027-07-11T13:45:00",
                        "arrival_time": "2027-07-11T15:50:00",
                        "stops": 0,
                    },
                },
                {
                    "ignav_id": "ignav-mixed-jx-ci",
                    "price": 3800,
                    "currency": "USD",
                    "outbound": {
                        "carrier_code": "JX",
                        "flight_number": "838",
                        "departure_time": "2027-07-04T14:55:00",
                        "arrival_time": "2027-07-04T18:45:00",
                        "stops": 0,
                    },
                    "inbound": {
                        "carrier_code": "CI",
                        "flight_number": "151",
                        "departure_time": "2027-07-11T09:55:00",
                        "arrival_time": "2027-07-11T11:55:00",
                        "stops": 0,
                    },
                },
            ]
        }

        with (
            patch("src.planner.service._get_serpapi_key", return_value="test-serp-key"),
            patch("src.planner.service._serpapi_request", side_effect=fake_serpapi_request) as serp_mock,
            patch("src.planner.service._client", return_value=(mock_client, Exception)),
        ):
            results = planner_service.search_draft(draft["id"])
            first_call_count = serp_mock.call_count
            # Known schedules avoid extra departure_token calls: only 2 market_scan calls!
            self.assertEqual(2, first_call_count)
            # Second search within 24h hits SQLite planner_search_cache -> 0 additional SerpApi calls!
            results_cached = planner_service.search_draft(draft["id"])
            self.assertEqual(first_call_count, serp_mock.call_count)
            self.assertEqual(len(results), len(results_cached))

        by_key = {planner_service.itinerary_key(r): r for r in results}
        # Both 2027-07-04 and 2027-07-05 have CI154+CI155
        self.assertIn("2027-07-04:CI154:2027-07-11:CI155", by_key)
        self.assertIn("2027-07-05:CI154:2027-07-11:CI155", by_key)
        # Mixed-airline JX838+CI151 is filtered out
        self.assertNotIn("2027-07-04:JX838:2027-07-11:CI151", by_key)
        ci_row = by_key["2027-07-04:CI154:2027-07-11:CI155"]
        self.assertEqual("中華航空", ci_row["airline"])
        self.assertEqual(32600.0, ci_row["amount"])
        self.assertEqual("TWD", ci_row["currency"])

        # IT206+IT207 merges SerpApi TWD price (23800) with Ignav's ignav_id and formats bags dict
        it_row = by_key["2027-07-04:IT206:2027-07-11:IT207"]
        self.assertEqual("台灣虎航", it_row["airline"])
        self.assertEqual(23800.0, it_row["amount"])
        self.assertEqual("ignav-it206-207", it_row["ignav_id"])
        self.assertEqual("serpapi+ignav", it_row["provider"])
        self.assertEqual("托運 1 件 · 手提 1 件", it_row["bags"])

    def test_p3_dual_api_live_lookup_bypasses_cache_and_presents_both_sources(self):
        payload = self._sample_draft_payload(children=[{"age_at_departure": 9}, {"age_at_departure": 7}])
        payload["destinations"] = ["NGO"]
        draft = planner_service.save_draft(payload)
        itin = {
            "origin": "TPE",
            "destination": "NGO",
            "outbound_date": "2027-07-11",
            "return_date": "2027-07-17",
            "outbound": {"flight_number": "CI154", "departure_time": "07:35", "arrival_time": "11:25", "stops": 0, "airline": "中華航空"},
            "inbound": {"flight_number": "CI155", "departure_time": "12:20", "arrival_time": "14:30", "stops": 0, "airline": "中華航空"},
            "airline": "中華航空",
            "amount": 64000.0,
            "currency": "TWD",
            "price_scope": "party_of_4",
            "provider": "serpapi",
            "ignav_id": None,
        }
        cand = planner_service.add_candidate(draft["id"], itin)

        # Seed 24h search cache to prove P3 booking-preview bypasses cache every time
        with planner_service._connection() as conn:
            ck = planner_service._cache_key("TPE", "NGO", "2027-07-11", "2027-07-17", 2, 2)
            conn.execute(
                "INSERT INTO planner_search_cache(cache_key,payload_json,cached_at) VALUES(?,?,CURRENT_TIMESTAMP)",
                (ck, json.dumps([itin])),
            )

        def fake_serpapi(params, endpoint="", timeout=25):
            self.assertEqual(2, params["adults"])
            self.assertEqual(2, params["children"])
            self.assertEqual("2027-07-11", params["outbound_date"])
            self.assertEqual("2027-07-17", params["return_date"])
            if params.get("booking_token") == "btok-ci154-155":
                return {
                    "search_metadata": {"google_flights_url": "https://www.google.com/travel/flights?booking=ci154"},
                    "booking_options": [
                        {
                            "together": {
                                "book_with": "China Airlines",
                                "marketed_as": ["CI 154", "CI 155"],
                                "price": 64780,
                                "currency": "TWD",
                                "price_scope": "party_of_4",
                                "baggage_prices": ["1 free carry-on", "1st checked bag free"],
                                "booking_request": {"url": "https://www.google.com/travel/clk/f?ci154"},
                            }
                        }
                    ],
                }
            if params.get("departure_token") == "dtok-ci154":
                return {
                    "search_metadata": {"google_flights_url": "https://www.google.com/travel/flights?ret=ci155"},
                    "best_flights": [
                        {
                            "flights": [
                                {
                                    "flight_number": "CI 155",
                                    "airline": "China Airlines",
                                    "departure_airport": {"id": "NGO", "time": "2027-07-17 12:20"},
                                    "arrival_airport": {"id": "TPE", "time": "2027-07-17 14:30"},
                                }
                            ],
                            "price": 64780,
                            "booking_token": "btok-ci154-155",
                        }
                    ],
                }
            return {
                "search_metadata": {"google_flights_url": "https://www.google.com/travel/flights?out=ci154"},
                "best_flights": [
                    {
                        "flights": [
                            {
                                "flight_number": "CI 154",
                                "airline": "China Airlines",
                                "departure_airport": {"id": "TPE", "time": "2027-07-11 07:35"},
                                "arrival_airport": {"id": "NGO", "time": "2027-07-11 11:25"},
                            }
                        ],
                        "price": 64780,
                        "departure_token": "dtok-ci154",
                    }
                ],
            }

        mock_client = MagicMock()
        mock_client.search_round_trip.return_value = {
            "itineraries": [
                {
                    "ignav_id": "ignav-ci154-155",
                    "price": 65200,
                    "currency": "TWD",
                    "price_scope": "party_total",
                    "outbound": {
                        "carrier_code": "CI",
                        "flight_number": "154",
                        "departure_time": "2027-07-11T07:35:00",
                        "arrival_time": "2027-07-11T11:25:00",
                        "stops": 0,
                    },
                    "inbound": {
                        "carrier_code": "CI",
                        "flight_number": "155",
                        "departure_time": "2027-07-17T12:20:00",
                        "arrival_time": "2027-07-17T14:30:00",
                        "stops": 0,
                    },
                }
            ]
        }
        mock_client.get_booking_links.return_value = {
            "booking_options": [
                {
                    "provider": "Trip.com",
                    "price": {"amount": 65200, "currency": "TWD"},
                    "price_scope": "party_total",
                    "url": "https://tw.trip.com/flights/ci154-155",
                    "terms": "含 23kg 托運",
                }
            ]
        }

        with (
            patch("src.planner.service._get_serpapi_key", return_value="serp-test-key"),
            patch("src.planner.service._serpapi_request", side_effect=fake_serpapi) as serp_mock,
            patch("src.planner.service._client", return_value=(mock_client, Exception)),
        ):
            preview1 = planner_service.preview_booking_candidate(cand["id"])
            self.assertEqual(3, serp_mock.call_count)  # market + departure_token + booking_token
            self.assertEqual(1, mock_client.search_round_trip.call_count)
            self.assertEqual(1, mock_client.get_booking_links.call_count)

            # Second preview MUST bypass cache and call both APIs again
            preview2 = planner_service.preview_booking_candidate(cand["id"])
            self.assertEqual(6, serp_mock.call_count)
            self.assertEqual(2, mock_client.search_round_trip.call_count)
            self.assertEqual(2, mock_client.get_booking_links.call_count)

            self.assertEqual("ready", preview2["status"])
            self.assertTrue(preview2["can_decide"])
            self.assertFalse(preview2["decision_persisted"])
            self.assertIsNone(planner_service.current_decision())

            serp_src = preview2["api_sources"]["serpapi"]
            ignav_src = preview2["api_sources"]["ignav"]
            self.assertEqual(64780.0, serp_src["amount"])
            self.assertEqual("party_of_4", serp_src["price_scope"])
            self.assertEqual("available", serp_src["status"])
            self.assertTrue(serp_src["verified_party_total"])
            self.assertEqual("https://www.google.com/travel/clk/f?ci154", serp_src["url"])
            self.assertTrue(serp_src["checked_at"])

            self.assertEqual(65200.0, ignav_src["amount"])
            self.assertEqual("party_total", ignav_src["price_scope"])
            self.assertEqual("available", ignav_src["status"])
            self.assertTrue(ignav_src["verified_party_total"])
            self.assertEqual("https://tw.trip.com/flights/ci154-155", ignav_src["url"])
            self.assertTrue(ignav_src["checked_at"])

            # Deciding within 24h freshness reuses the verified quotes without extra API calls
            decided = planner_service.decide_candidate(cand["id"])
            self.assertEqual(6, serp_mock.call_count)
            self.assertEqual(2, mock_client.search_round_trip.call_count)
            self.assertTrue(decided["decision_persisted"])
            self.assertEqual(cand["id"], planner_service.current_decision()["candidate_id"])

    def test_p3_rejects_mismatched_dates_or_flight_numbers_and_never_uses_schedule_templates(self):
        payload = self._sample_draft_payload(children=[])
        payload["destinations"] = ["NGO"]
        draft = planner_service.save_draft(payload)
        itin = {
            "origin": "TPE",
            "destination": "NGO",
            "outbound_date": "2027-07-11",
            "return_date": "2027-07-17",
            "outbound": {"flight_number": "CI154", "departure_time": "07:35", "arrival_time": "11:25", "stops": 0, "airline": "中華航空"},
            "inbound": {"flight_number": "CI155", "departure_time": "12:20", "arrival_time": "14:30", "stops": 0, "airline": "中華航空"},
            "airline": "中華航空",
            "amount": 32000.0,
            "currency": "TWD",
            "price_scope": "party_of_2",
            "provider": "serpapi",
            "ignav_id": "stale-ignav-id",
        }
        cand = planner_service.add_candidate(draft["id"], itin)

        # SerpApi returns CI154 on outbound, but return flight is CI151 (wrong flight number) or no departure_token
        def fake_serpapi_mismatch(params, endpoint="", timeout=25):
            if params.get("departure_token"):
                return {
                    "best_flights": [
                        {
                            "flights": [
                                {
                                    "flight_number": "CI 151",
                                    "departure_airport": {"id": "NGO", "time": "2027-07-17 09:55"},
                                    "arrival_airport": {"id": "TPE", "time": "2027-07-17 11:55"},
                                }
                            ],
                            "price": 31000,
                        }
                    ]
                }
            return {
                "best_flights": [
                    {
                        "flights": [
                            {
                                "flight_number": "CI 154",
                                "departure_airport": {"id": "TPE", "time": "2027-07-11 07:35"},
                                "arrival_airport": {"id": "NGO", "time": "2027-07-11 11:25"},
                            }
                        ],
                        "price": 31000,
                        "departure_token": "dtok-ci154",
                    }
                ]
            }

        # Ignav returns CI154 + CI155 but on wrong return date (2027-07-18 instead of 2027-07-17)
        mock_client = MagicMock()
        mock_client.search_round_trip.return_value = {
            "itineraries": [
                {
                    "ignav_id": "ignav-wrong-date",
                    "price": 30000,
                    "currency": "TWD",
                    "price_scope": "party_total",
                    "outbound": {
                        "carrier_code": "CI",
                        "flight_number": "154",
                        "departure_time": "2027-07-11T07:35:00",
                        "arrival_time": "2027-07-11T11:25:00",
                        "stops": 0,
                    },
                    "inbound": {
                        "carrier_code": "CI",
                        "flight_number": "155",
                        "departure_time": "2027-07-18T12:20:00",
                        "arrival_time": "2027-07-18T14:30:00",
                        "stops": 0,
                    },
                }
            ]
        }

        with (
            patch("src.planner.service._get_serpapi_key", return_value="serp-key"),
            patch("src.planner.service._serpapi_request", side_effect=fake_serpapi_mismatch),
            patch("src.planner.service._client", return_value=(mock_client, Exception)),
        ):
            preview = planner_service.preview_booking_candidate(cand["id"])
            self.assertEqual("missing_provider_offer", preview["status"])
            self.assertFalse(preview["can_decide"])
            self.assertEqual("missing_provider_offer", preview["api_sources"]["serpapi"]["status"])
            self.assertEqual("missing_provider_offer", preview["api_sources"]["ignav"]["status"])
            # Must not call get_booking_links with stale-ignav-id when live search didn't match
            self.assertEqual(0, mock_client.get_booking_links.call_count)

    def test_p3_blocks_decision_for_per_person_unknown_scope_or_missing_url_and_keeps_links_without_price(self):
        draft = planner_service.save_draft(self._sample_draft_payload())  # 2 adults + 2 children = 4 pax
        cand = planner_service.add_candidate(draft["id"], self._sample_itinerary())

        # SerpApi returns per_person price; Ignav returns one unknown-scope price and one link-only option without price
        def fake_serpapi_per_person(params, endpoint="", timeout=25):
            if params.get("departure_token"):
                return {
                    "search_metadata": {"google_flights_url": "https://www.google.com/travel/flights?test=1"},
                    "best_flights": [
                        {
                            "flights": [
                                {
                                    "flight_number": "BR 109",
                                    "departure_airport": {"id": "KIX", "time": "2027-07-17 12:45"},
                                    "arrival_airport": {"id": "TPE", "time": "2027-07-17 15:05"},
                                }
                            ],
                            "price": 15800,
                            "price_scope": "per_person",
                        }
                    ],
                }
            return {
                "best_flights": [
                    {
                        "flights": [
                            {
                                "flight_number": "BR 108",
                                "departure_airport": {"id": "TPE", "time": "2027-07-11 07:55"},
                                "arrival_airport": {"id": "KIX", "time": "2027-07-11 11:35"},
                            }
                        ],
                        "price": 15800,
                        "departure_token": "tok-br108",
                    }
                ]
            }

        mock_client = MagicMock()
        mock_client.search_round_trip.return_value = {
            "itineraries": [
                {
                    "ignav_id": "offer-1",
                    "price": 59000,
                    "currency": "TWD",
                    "price_scope": "unknown",
                    "outbound": {"carrier_code": "BR", "flight_number": "108", "departure_time": "2027-07-11T07:55:00", "arrival_time": "2027-07-11T11:35:00", "stops": 0},
                    "inbound": {"carrier_code": "BR", "flight_number": "109", "departure_time": "2027-07-17T12:45:00", "arrival_time": "2027-07-17T15:05:00", "stops": 0},
                }
            ]
        }
        mock_client.get_booking_links.return_value = {
            "booking_options": [
                {
                    "provider": "OTA Unknown Scope",
                    "price": {"amount": 59000, "currency": "TWD"},
                    "price_scope": "unknown",
                    "url": "https://booking.example.com/unknown",
                },
                {
                    "provider": "Official Link Only",
                    "price": None,
                    "price_scope": "unknown",
                    "url": "https://booking.example.com/link-only",
                },
            ]
        }

        with (
            patch("src.planner.service._get_serpapi_key", return_value="serp-key"),
            patch("src.planner.service._serpapi_request", side_effect=fake_serpapi_per_person),
            patch("src.planner.service._client", return_value=(mock_client, Exception)),
        ):
            decision = planner_service.decide_candidate(cand["id"])
            self.assertEqual("unverified_quotes", decision["status"])
            self.assertFalse(decision["can_decide"])
            self.assertFalse(decision["decision_persisted"])
            self.assertIsNone(planner_service.current_decision())

            # Link without price is preserved with url and status="links_only" / status_label="未提供價格"
            link_only_opt = next(o for o in decision["booking_options"] if o["provider"] == "Official Link Only")
            self.assertIsNone(link_only_opt["amount"])
            self.assertEqual("https://booking.example.com/link-only", link_only_opt["url"])
            self.assertEqual("links_only", link_only_opt["status"])
            self.assertEqual("未提供價格", link_only_opt["status_label"])
            self.assertFalse(link_only_opt["verified_party_total"])

            # HTTP endpoint also rejects unverified decision with 422
            with self.assertRaises(server.HTTPException) as ctx:
                server.planner_decide_candidate(cand["id"])
            self.assertEqual(422, ctx.exception.status_code)

    def test_p3_freshness_expiry_over_24_hours_triggers_requery_on_decide(self):
        draft = planner_service.save_draft(self._sample_draft_payload())
        cand = planner_service.add_candidate(draft["id"], self._sample_itinerary())

        mock_client = MagicMock()
        mock_client.get_booking_links.return_value = {
            "booking_options": [
                {
                    "provider": "EVA Air Official",
                    "price": {"amount": 58400, "currency": "TWD"},
                    "price_scope": "party_total",
                    "url": "https://booking.example.com/eva",
                }
            ]
        }

        with patch("src.planner.service._client", return_value=(mock_client, Exception)):
            preview = planner_service.preview_booking_candidate(cand["id"])
            self.assertTrue(preview["can_decide"])
            self.assertTrue(preview["is_fresh"])
            self.assertEqual(1, mock_client.get_booking_links.call_count)

            # Age the stored quote to 25 hours ago (> 24h freshness limit)
            stale_ts = "2020-01-01T00:00:00+00:00"
            with planner_service._connection() as conn:
                conn.execute("UPDATE planner_booking_quotes SET observed_at=? WHERE candidate_id=?", (stale_ts, cand["id"]))
                conn.execute("UPDATE planner_p3_quote_runs SET checked_at=? WHERE candidate_id=?", (stale_ts, cand["id"]))

            # Stored quote should now be evaluated as stale (is_fresh=False, can_decide=False)
            loaded = planner_service._load_stored_p3_quotes(
                cand["id"], cand["itinerary"], draft["travelers"], 3, 1, False
            )
            self.assertFalse(loaded["is_fresh"])
            self.assertFalse(loaded["can_decide"])
            self.assertEqual("stale_quotes", loaded["status"])

            # Calling decide_candidate when stored quote is stale (>24h) must re-query the API live
            decided = planner_service.decide_candidate(cand["id"])
            self.assertEqual(2, mock_client.get_booking_links.call_count)
            self.assertTrue(decided["is_fresh"])
            self.assertTrue(decided["can_decide"])
            self.assertTrue(decided["decision_persisted"])


if __name__ == "__main__":
    unittest.main()
