import unittest
import json
from unittest.mock import patch
import test_nagoya_flight_monitor as baseline_tests
from test_nagoya_flight_monitor import m, CFG, offer


class BookingVerificationTests(unittest.TestCase):
    def row(self, price=63064, changes=None):
        row = m.build_itinerary(m.candidate(offer(), CFG),
                               m.candidate(offer(inbound=True, price=price), CFG, True),
                               m.iso_now(), {}, {}, CFG)
        row['price_changes'] = changes or []
        return row

    def test_only_price_or_purchase_triggers(self):
        self.assertEqual(m.booking_reasons(self.row(), CFG), [])
        self.assertEqual(m.booking_reasons(self.row(changes=['new_itinerary']), CFG), [])
        self.assertEqual(m.booking_reasons(self.row(changes=['new_airline']), CFG), [])
        self.assertIn('near_target', m.booking_reasons(self.row(55000), CFG))
        for change in ('new_low', 'drop_5_percent'):
            self.assertIn(change, m.booking_reasons(self.row(changes=[change]), CFG))
        self.assertEqual(m.booking_reasons(self.row(), CFG, True), ['purchase'])

    def response(self, price=63064):
        return {'selected_flights': [offer(), offer(inbound=True)],
                'booking_options': [{'together': {'book_with': 'China Airlines',
                    'price': price, 'baggage_prices': ['1st checked bag free']}}]}

    def test_exact_quote_verifies_price_and_literal_baggage(self):
        row = self.row()
        evidence = m.verify_booking(self.response(), row, CFG, m.iso_now())
        self.assertEqual(evidence['price'], 63064)
        self.assertEqual(evidence['baggage_prices'], ['1st checked bag free'])
        self.assertEqual(evidence['passengers'], {'adults': 2, 'children': 2})

    def test_mismatch_wrong_flights_or_separate_tickets_do_not_verify(self):
        self.assertIsNone(m.verify_booking(self.response(17448), self.row(), CFG, m.iso_now()))
        data = self.response()
        data['selected_flights'][1]['flights'][0]['flight_number'] = 'CI 151'
        with self.assertRaises(ValueError):
            m.verify_booking(data, self.row(), CFG, m.iso_now())
        data = self.response()
        data['booking_options'][0]['separate_tickets'] = True
        self.assertIsNone(m.verify_booking(data, self.row(), CFG, m.iso_now()))

    def test_verified_price_still_enters_raw_price_history(self):
        row = {'route_key': m.route_key(CFG), 'status': 'observed',
               'price_scope': 'family_total', 'currency': 'TWD',
               'displayed_price_twd': '63064', 'itinerary_key': 'CI154+CI151'}
        self.assertEqual(m.itinerary_lows([row], m.route_key(CFG)), {'CI154+CI151': 63064})


class BookingIntegrationTests(unittest.TestCase):
    setUp = baseline_tests.MonitorTests.setUp
    account = baseline_tests.MonitorTests.account

    def run_case(self, used=100, booking=None, purchase=True):
        cfg = dict(CFG, booking_verifications_per_run=1)
        m.CONFIG.write_text(json.dumps(cfg))
        row = BookingVerificationTests().row()
        row['price_changes'] = ['new_low']  # Retained events must not retrigger a paid check.
        self.latest.write_text(json.dumps({'route': cfg, 'itineraries': [row],
            'market_candidates': [m.candidate(offer(), cfg)],
            'outbound_refresh': {n: m.iso_now() for n in cfg['full_query_outbounds']}}))
        responses = [self.account(used), {'best_flights': [offer()]}, self.account(used + 1)]
        if purchase and used < 224:
            responses += [booking if booking is not None else BookingVerificationTests().response(),
                          self.account(used + 2)]
        with patch.dict(m.os.environ, {'SERPAPI_KEY': 'fake-secret'}), \
                patch.object(m, 'request_json', side_effect=responses) as request:
            result = m.main(purchase_itinerary=row['itinerary_key'] if purchase else None)
        return result, request, json.loads(self.latest.read_text())

    def test_explicit_purchase_exact_match_costs_one_extra_and_audits_without_price_observation(self):
        result, request, data = self.run_case()
        self.assertEqual(result, 0)
        self.assertEqual(data['searches_used'], 2)
        self.assertEqual(data['account_calls'], 3)
        self.assertEqual(data['itineraries'][0]['family_total_twd'], 63064)
        params = request.call_args_list[3].args[0]
        self.assertIn('selected_flights_json', params)
        self.assertEqual(set(json.loads(params['selected_flights_json'])), {'outbound', 'return'})
        self.assertNotIn('departure_token', params)
        rows, _ = m.read_history(self.latest.parent / 'itinerary_history.csv')
        self.assertEqual([r['record_type'] for r in rows], ['verification'])

    def test_retained_price_change_does_not_trigger(self):
        result, _, data = self.run_case(purchase=False)
        self.assertEqual(result, 0)
        self.assertEqual(data['searches_used'], 1)
        self.assertEqual(data['booking_verification_checks'], [])
        self.assertIsNone(data['itineraries'][0]['family_total_twd'])

    def test_booking_failure_preserves_primary_snapshot_and_unknown_scope(self):
        result, _, data = self.run_case(booking=RuntimeError('secret URL must never be logged'))
        self.assertEqual(result, 0)
        self.assertEqual(data['booking_verification_checks'][0]['status'], 'error')
        self.assertIsNone(data['itineraries'][0]['family_total_twd'])
        self.assertNotIn('secret URL', json.dumps(data))

    def test_counter_lag_guard_blocks_booking_at_market_only_boundary(self):
        result, _, data = self.run_case(used=224)
        self.assertEqual(result, 0)
        self.assertEqual(data['searches_used'], 1)
        self.assertEqual(data['booking_verification_checks'][0]['deferred_reason'], 'quota')
