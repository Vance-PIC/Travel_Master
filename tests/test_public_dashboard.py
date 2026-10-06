import copy
import json
import re
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from scripts.build_public_dashboard import project_flights, project_hotels, read_snapshot

NOW = datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
CHECKED = '2026-10-05T15:00:00+08:00'


def quote(price=68466):
    return {'displayed_price_twd': price, 'price_scope': 'family_total',
            'outbound_flight': 'CI150', 'inbound_flight': 'CI151',
            'outbound_departure': '08:00', 'outbound_arrival': '12:00',
            'inbound_departure': '13:00', 'inbound_arrival': '15:00',
            'family_total_twd': price, 'checked_at': CHECKED,
            'price_verification': {'price': price, 'verified_at': CHECKED,
                                   'quote_checked_at': CHECKED},
            'passengers': {'children': 2}, 'raw_response': {'secret': 'PRIVATE'}}


class PublicProjectionTests(unittest.TestCase):
    def test_incomplete_round_trips_are_rejected(self):
        for field in ('outbound_flight', 'inbound_flight', 'outbound_departure',
                      'outbound_arrival', 'inbound_departure', 'inbound_arrival'):
            for value in (None, '', '   ', 123):
                with self.subTest(field=field, value=value):
                    item = quote(1)
                    item[field] = value
                    self.assertEqual(project_flights({'itineraries': [item]}, NOW), [])
            with self.subTest(missing=field):
                item = quote(1)
                del item[field]
                self.assertEqual(project_flights({'itineraries': [item]}, NOW), [])

    def test_invalid_round_trips_do_not_displace_valid_top_five(self):
        missing_return = quote(0)
        del missing_return['inbound_flight']
        missing_time = quote(0)
        del missing_time['outbound_arrival']
        rows = project_flights({'itineraries': [missing_return, missing_time]
                                + [quote(p) for p in range(7, 0, -1)]}, NOW)
        self.assertEqual([row['displayed_price_twd'] for row in rows], [1, 2, 3, 4, 5])

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


class PublicPageTests(unittest.TestCase):
    def test_flight_status_describes_only_listed_observations(self):
        from scripts.build_public_dashboard import render_page
        html = render_page(project_flights({'itineraries': [quote()]}, NOW), [], {})
        self.assertIn('所列機票最新觀測：' + CHECKED, html)
        self.assertNotIn('機票最新有效觀測', html)

    def test_render_escapes_and_ignores_unknown_fields(self):
        from scripts.build_public_dashboard import render_page
        html = render_page([{'airline': '<script>alert(1)</script>', 'checked_at': CHECKED,
                             'stale': True, 'child_ages': 'PRIVATE_CHILD',
                             'raw_response': 'PRIVATE_RAW'}], [], {'private': 'PRIVATE_STATUS'})
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn(CHECKED, html)
        self.assertIn('資料過期', html)
        for value in ('PRIVATE_CHILD', 'PRIVATE_RAW', 'PRIVATE_STATUS', 'child_ages'):
            self.assertNotIn(value, html)

    def test_build_page_omits_private_snapshot_data(self):
        from scripts.build_public_dashboard import build_page
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flights = root / 'travel/nagoya/flights'
            hotels = root / 'travel/nagoya/hotels/one'
            flights.mkdir(parents=True)
            hotels.mkdir(parents=True)
            item = quote()
            item['airline'] = 'Safe airline'
            item['child_ages'] = 'PRIVATE_AGES'
            flights.joinpath('latest.json').write_text(json.dumps({'itineraries': [item],
                'budget': 'PRIVATE_BUDGET', 'daily_itinerary': 'PRIVATE_DAY',
                'SERPAPI_KEY': 'PRIVATE_KEY'}), encoding='utf-8')
            hotels.joinpath('latest.json').write_text(json.dumps({'booking_baseline': 'PRIVATE_BASELINE',
                'observations': [{'hotel_name': 'Safe hotel', 'total_amount': 100,
                'query_currency': 'JPY', 'observed_at': CHECKED}]}), encoding='utf-8')
            html = build_page(root, NOW + timedelta(days=3))
            self.assertIn('Safe airline', html)
            self.assertIn('Safe hotel', html)
            self.assertIn(CHECKED, html)
            self.assertIn('資料過期', html)
            for value in ('PRIVATE_', 'SERPAPI_KEY', 'raw_response', 'booking_baseline',
                          'daily_itinerary', 'child_ages', '2030-01-01'):
                self.assertNotIn(value, html)

    def test_source_status_distinguishes_missing_corrupt_and_empty(self):
        from scripts.build_public_dashboard import build_page
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIn('無可用報價', build_page(root, NOW))
            path = root / 'travel/nagoya/flights/latest.json'
            path.parent.mkdir(parents=True)
            path.write_text('{SECRET_ERROR', encoding='utf-8')
            html = build_page(root, NOW)
            self.assertIn('資料無法讀取', html)
            self.assertNotIn('SECRET_ERROR', html)
            path.write_text('{"itineraries": []}', encoding='utf-8')
            self.assertIn('無有效觀測', build_page(root, NOW))

class PublicPagesWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (Path(__file__).resolve().parents[1] /
                         '.github/workflows/publish-price-dashboard.yml').read_text(encoding='utf-8')

    def test_trigger_and_trusted_checkout(self):
        workflow = self.workflow
        for required in ('workflow_dispatch:', 'workflow_run:', 'types: [completed]',
                         "workflows: ['Nagoya SerpApi flight monitor', 'Hotel monitor executor']",
                         'branches: [master]',
                         "github.event_name != 'workflow_run' || github.event.workflow_run.head_branch == 'master'",
                         'ref: master'):
            self.assertIn(required, workflow)
        paths = workflow.split('    paths:\n', 1)[1].split('  workflow_run:', 1)[0]
        self.assertEqual(re.findall(r"- '([^']+)'", paths), [
            'scripts/build_public_dashboard.py', 'site/public_price_template.html',
            '.github/workflows/publish-price-dashboard.yml'])

    def test_no_fare_api_calls_or_private_artifacts(self):
        workflow = self.workflow
        for forbidden in ('schedule:', 'SERPAPI_KEY', 'SEARCHAPI_KEY', 'Ignav_KEY',
                          'nagoya_flight_monitor.py', 'hotel_executor.py',
                          'download-artifact', 'contents: write', 'git add .',
                          'actions/upload-pages-artifact', 'actions/deploy-pages',
                          'travel/nagoya/*', 'cp -r', 'rsync'):
            self.assertNotIn(forbidden, workflow)
        self.assertIn('python scripts/build_public_dashboard.py --output _site', workflow)
        self.assertIn('cp _site/index.html public-site/index.html', workflow)
        self.assertIn('git -C public-site add -- index.html', workflow)
        self.assertIn('git -C public-site push origin HEAD:main', workflow)

    def test_cross_repository_publish_scope_and_token_guard(self):
        for required in ('actions/checkout@v4', 'persist-credentials: false',
                         'repository: Vance-PIC/Travel_Master_Prices', 'ref: main',
                         'path: public-site', 'token: ${{ secrets.PUBLIC_PAGES_TOKEN }}',
                         'PUBLIC_PAGES_TOKEN: ${{ secrets.PUBLIC_PAGES_TOKEN }}',
                         'if [ -z "$PUBLIC_PAGES_TOKEN" ]; then',
                         'contents: read', 'group: public-price-dashboard-pages',
                         'cancel-in-progress: false'):
            self.assertIn(required, self.workflow)
        self.assertNotIn('https://${{ secrets.PUBLIC_PAGES_TOKEN }}', self.workflow)
        self.assertNotIn('echo "$PUBLIC_PAGES_TOKEN"', self.workflow)


if __name__ == '__main__':
    unittest.main()
