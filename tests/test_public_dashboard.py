import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from scripts.build_public_dashboard import project_flights, project_hotels, read_snapshot

NOW = datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
CHECKED = '2026-10-05T15:00:00+08:00'


def quote(price=68466):
    return {'displayed_price_twd': price, 'price_scope': 'family_total',
            'family_total_twd': price, 'checked_at': CHECKED,
            'price_verification': {'price': price, 'verified_at': CHECKED,
                                   'quote_checked_at': CHECKED},
            'passengers': {'children': 2}, 'raw_response': {'secret': 'PRIVATE'}}


class PublicProjectionTests(unittest.TestCase):
    def test_flights_order_scope_and_whitelist(self):
        unverified = quote(63090)
        unverified['price_scope'] = 'unknown'
        snapshot = {'route': {'origin': 'TPE', 'destination': 'NGO',
                             'passengers': {'children': 2}},
                    'itineraries': [quote(), unverified, quote(-1)],
                    'market_candidates': [quote(1)]}
        before = copy.deepcopy(snapshot)
        rows = project_flights(snapshot, NOW)
        self.assertEqual([r['displayed_price_twd'] for r in rows], [63090, 68466])
        self.assertEqual(rows[0]['price_label'], 'API 顯示價格，未驗證為家庭總價')
        self.assertEqual(rows[1]['price_label'], '已驗證家庭總價')
        self.assertNotIn('PRIVATE', str(rows))
        self.assertNotIn('passengers', str(rows))
        self.assertEqual(snapshot, before)

    def test_verification_must_match_current_quote(self):
        for field, value in [('quote_checked_at', '2026-10-04T15:00:00+08:00'),
                             ('verified_at', None), ('price', 1)]:
            with self.subTest(field=field):
                row = quote()
                row['price_verification'][field] = value
                result = project_flights({'itineraries': [row]}, NOW)[0]
                self.assertEqual(result['price_scope'], 'unknown')
                self.assertEqual(result['baggage_status'], 'unknown')
                self.assertEqual(result['price_label'], 'API 顯示價格，未驗證為家庭總價')

    def test_invalid_prices_times_and_top_five(self):
        invalid = [quote(p) for p in [-1, float('nan'), float('inf'), True, '15', None]]
        for timestamp in [None, 'broken', '2026-10-05T07:00:00']:
            row = quote()
            row['checked_at'] = timestamp
            invalid.append(row)
        rows = project_flights({'itineraries': invalid + [quote(p) for p in range(7, 0, -1)]}, NOW)
        self.assertEqual([r['displayed_price_twd'] for r in rows], [1, 2, 3, 4, 5])

    def test_timezone_and_48_hour_expiry(self):
        row = quote()
        instant = datetime(2026, 10, 5, 7, tzinfo=timezone.utc)
        self.assertFalse(project_flights({'itineraries': [row]}, instant + timedelta(hours=48))[0]['stale'])
        self.assertTrue(project_flights({'itineraries': [row]}, instant + timedelta(hours=48, seconds=1))[0]['stale'])
        self.assertEqual(project_flights({'itineraries': [row]}, NOW)[0]['checked_at'], CHECKED)

    def test_hotels_keep_original_currency_and_observation_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'one').mkdir()
            observation = {'hotel_name': 'Hotel', 'total_amount': 76273, 'nightly_amount': 12712,
                           'query_currency': 'JPY', 'observed_at': CHECKED,
                           'stay': {'check_in': '2027-07-11', 'check_out': '2027-07-17'},
                           'source': 'Booking.com', 'comparison_status': 'pending_confirmation',
                           'party': {'children': 2}, 'booking_baseline': {'amount': 1}}
            (root / 'one' / 'latest.json').write_text(json.dumps({'checked_at': '2030-01-01T00:00:00Z',
                                                               'observations': [observation]}), encoding='utf-8')
            rows = project_hotels(root, NOW)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['query_currency'], 'JPY')
            self.assertEqual(rows[0]['total_amount'], 76273)
            self.assertEqual(rows[0]['observed_at'], CHECKED)
            self.assertNotIn('party', str(rows))
            self.assertNotIn('booking_baseline', str(rows))
            self.assertNotIn('twd', str(rows).lower())

    def test_large_integer_flight_price_does_not_abort_projection(self):
        amount = 10 ** 400
        rows = project_flights({'itineraries': [quote(amount), quote(1)]}, NOW)
        self.assertEqual([row['displayed_price_twd'] for row in rows], [1, amount])
        self.assertEqual(rows[1]['price_label'], '已驗證家庭總價')

    def test_large_integer_hotel_price_does_not_abort_projection(self):
        amount = 10 ** 400
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'one').mkdir()
            observations = [{'hotel_name': 'Hotel', 'total_amount': price,
                             'nightly_amount': price, 'query_currency': 'JPY',
                             'observed_at': CHECKED} for price in [amount, 1]]
            (root / 'one' / 'latest.json').write_text(
                json.dumps({'observations': observations}), encoding='utf-8')
            rows = project_hotels(root, NOW)
            self.assertEqual([row['total_amount'] for row in rows], [amount, 1])
            self.assertEqual(rows[0]['nightly_amount'], amount)
    def test_missing_invalid_and_malformed_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'latest.json'
            self.assertEqual(read_snapshot(path), ({}, '無可用報價'))
            path.write_text('{secret invalid', encoding='utf-8')
            self.assertEqual(read_snapshot(path), ({}, '資料無法讀取'))
            path.write_text('[]', encoding='utf-8')
            self.assertEqual(read_snapshot(path), ({}, '資料無法讀取'))
            self.assertEqual(project_hotels(Path(directory), NOW), [])
        for data in [None, [], {'itineraries': None}, {'itineraries': [None]}]:
            self.assertEqual(project_flights(data, NOW), [])


if __name__ == '__main__':
    unittest.main()
