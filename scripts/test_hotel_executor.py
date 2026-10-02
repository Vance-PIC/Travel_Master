import copy
import json
from pathlib import Path
import tempfile
import unittest
from hotel_executor import assess, persist, recover, execute, report, invalid_property_token_error
from hotel_searchapi import SearchAPIError


class CountedClient:
    def __init__(self, replies, limit=5):
        self.replies = iter(replies)
        self.limit = limit
        self.attempts = 0
        self.calls = []

    def search(self, params):
        if self.attempts >= self.limit:
            raise RuntimeError('SearchAPI request budget exhausted')
        self.attempts += 1
        self.calls.append(params)
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def monitor(stage='candidate_search'):
    return {'monitor_id': 'test', 'stage': stage, 'stay': {'check_in': '2027-07-11', 'check_out': '2027-07-17'},
            'party': {'adults': 2, 'children': 2, 'child_ages': [9, 7], 'rooms': 1},
            'hard_filters': {'min_room_size_m2': 30, 'beds': {'count': 2, 'type': 'twin'}, 'smoking': 'non-smoking', 'location': {'anchor': 'airport'}},
            'hotel_identity': {'source_ids': {'searchapi.io': 'hotel1'}},
            'room_baseline': {'name': 'Twin', 'size_m2': 39, 'beds': {'count': 2, 'type': 'twin'}, 'smoking': 'non-smoking'},
            'booking_baseline': {'amount': 77836, 'currency': 'JPY', 'source': 'order', 'price_scope': 'total_stay_all_rooms_party',
                                 'tax_fee_inclusion': 'included', 'cancellation': {'deadline': 'date+zone', 'penalty': 0}, 'payment': {'when': 'now'}, 'benefits': []},
            'alert': {'amount': 70000, 'currency': 'JPY', 'price_scope': 'total_stay_all_rooms_party'}}


def quote(m):
    vals = {'hotel_data_id': 'hotel1', 'stay': m['stay'], 'party': m['party'], 'availability': True,
            'room_size_m2': 39, 'beds': {'count': 2, 'type': 'twin'}, 'smoking': 'non-smoking', 'location': True,
            'currency': 'JPY', 'price_scope': 'total_stay_all_rooms_party', 'tax_fee_inclusion': 'included',
            'cancellation': m['booking_baseline']['cancellation'], 'payment': {'when': 'now'}, 'benefits': [], 'eligibility': True}
    return {'source': 'OTA', 'room_name': 'Other name', 'total_amount': 69999, 'observed_at': '2026-10-01T00:00:00+00:00',
            'evidence': {k: {'literal_value': v, 'source': 'supplier', 'repo_path': 'fixture.json', 'observed_at': '2026-10-01T00:00:00+00:00'} for k, v in dict(vals, total_amount=69999).items()}}


class ExecutorTests(unittest.TestCase):
    def test_trusted_legacy_resolution_reuses_property_in_one_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'persistence_root': 'hotels', 'execution': {'query_enabled': True},
                   'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW'},
                   'monitors': [monitor('booked_room_compare')]}
            m = cfg['monitors'][0]
            m['hotel_identity']['name'] = 'Hotel'
            directory = Path(tmp)/'hotels/test'
            directory.mkdir(parents=True)
            (directory/'property-resolution.json').write_text(json.dumps({
                'schema_version': 1, 'provider': 'searchapi.io', 'data_id': 'hotel1',
                'hotel_name': 'Hotel', 'property_token': 'old-token',
                'evidence': {'source': 'searchapi.io/google_hotels',
                             'source_path': 'properties[0].property_token',
                             'observed_at': '2026-10-01T00:00:00+00:00'}}))
            client = CountedClient([{'property': {'name': 'Hotel', 'data_id': 'hotel1',
                                                  'property_token': 'old-token', 'featured_offers': []}}])
            result = execute(cfg, 'test', Path(tmp), client)
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['attempted_requests'], 1)
            self.assertEqual([call['engine'] for call in client.calls], ['google_hotels_property'])
            self.assertEqual(client.calls[0]['property_token'], 'old-token')
            self.assertEqual(json.loads((directory/'property-resolution.json').read_text())['monitor_id'], 'test')

    def test_missing_resolution_discovers_then_saves_monitor_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'persistence_root': 'hotels', 'execution': {'query_enabled': True},
                   'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW'},
                   'monitors': [monitor('booked_room_compare')]}
            cfg['monitors'][0]['hotel_identity']['name'] = 'Hotel'
            listing = {'properties': [{'type': 'hotel', 'name': 'Hotel', 'data_id': 'hotel1',
                                       'property_token': 'new-token'}]}
            detail = {'property': {'name': 'Hotel', 'data_id': 'hotel1', 'property_token': 'new-token'}}
            client = CountedClient([listing, detail])
            result = execute(cfg, 'test', Path(tmp), client)
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['attempted_requests'], 2)
            self.assertEqual([call['engine'] for call in client.calls], ['google_hotels', 'google_hotels_property'])
            saved = json.loads((Path(tmp)/'hotels/test/property-resolution.json').read_text())
            self.assertEqual((saved['monitor_id'], saved['provider'], saved['data_id']),
                             ('test', 'searchapi.io', 'hotel1'))
            self.assertEqual(saved['configured_hotel_name'], 'Hotel')

    def test_resolution_without_token_discovers_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'persistence_root': 'hotels', 'execution': {'query_enabled': True},
                   'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW'},
                   'monitors': [monitor('booked_room_compare')]}
            cfg['monitors'][0]['hotel_identity']['name'] = 'Hotel'
            directory = Path(tmp)/'hotels/test'
            directory.mkdir(parents=True)
            (directory/'property-resolution.json').write_text(json.dumps({
                'schema_version': 2, 'monitor_id': 'test', 'provider': 'searchapi.io',
                'data_id': 'hotel1', 'hotel_name': 'Hotel', 'configured_hotel_name': 'Hotel',
                'property_token': None, 'evidence': {'source': 'searchapi.io/google_hotels',
                    'source_path': 'properties[0].property_token', 'observed_at': '2026-10-01T00:00:00+00:00'}}))
            client = CountedClient([
                {'properties': [{'type': 'hotel', 'name': 'Hotel', 'data_id': 'hotel1',
                                 'property_token': 'new-token'}]},
                {'property': {'name': 'Hotel', 'data_id': 'hotel1', 'property_token': 'new-token'}}])
            result = execute(cfg, 'test', Path(tmp), client)
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['attempted_requests'], 2)
            self.assertEqual([call['engine'] for call in client.calls],
                             ['google_hotels', 'google_hotels_property'])
            self.assertEqual(json.loads((directory/'property-resolution.json').read_text())['property_token'],
                             'new-token')

    def test_explicit_invalid_cached_token_safely_refreshes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'persistence_root': 'hotels', 'execution': {'query_enabled': True},
                   'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW'},
                   'monitors': [monitor('booked_room_compare')]}
            cfg['monitors'][0]['hotel_identity']['name'] = 'Hotel'
            directory = Path(tmp)/'hotels/test'
            directory.mkdir(parents=True)
            (directory/'property-resolution.json').write_text(json.dumps({
                'schema_version': 2, 'monitor_id': 'test', 'provider': 'searchapi.io',
                'data_id': 'hotel1', 'hotel_name': 'Hotel', 'configured_hotel_name': 'Hotel',
                'property_token': 'old-token', 'evidence': {'source': 'searchapi.io/google_hotels',
                    'source_path': 'properties[0].property_token', 'observed_at': '2026-10-01T00:00:00+00:00'}}))
            invalid = SearchAPIError({'provider': 'searchapi.io', 'category': 'http_error',
                'http_status': 400, 'error_type': 'InvalidParameter',
                'message': 'Invalid property_token', 'request_parameters': {'engine': 'google_hotels_property'}})
            listing = {'properties': [{'type': 'hotel', 'name': 'Hotel', 'data_id': 'hotel1',
                                       'property_token': 'new-token'}]}
            detail = {'property': {'name': 'Hotel', 'data_id': 'hotel1', 'property_token': 'new-token'}}
            client = CountedClient([invalid, listing, detail])
            result = execute(cfg, 'test', Path(tmp), client)
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['attempted_requests'], 3)
            self.assertEqual([call['engine'] for call in client.calls],
                             ['google_hotels_property', 'google_hotels', 'google_hotels_property'])
            self.assertEqual(json.loads((directory/'property-resolution.json').read_text())['property_token'], 'new-token')
            saved_snapshot = (directory/'latest.json').read_bytes()
            wrong_hotel = {'property': {'name': 'Other Hotel', 'data_id': 'other-id',
                                        'property_token': 'third-token'}}
            client = CountedClient([invalid,
                {'properties': [{'type': 'hotel', 'name': 'Hotel', 'data_id': 'hotel1',
                                 'property_token': 'third-token'}]}, wrong_hotel])
            self.assertEqual(execute(cfg, 'test', Path(tmp), client)['status'], 'error')
            self.assertEqual(client.attempts, 3)
            self.assertEqual((directory/'latest.json').read_bytes(), saved_snapshot)
            self.assertEqual(json.loads((directory/'property-resolution.json').read_text())['property_token'],
                             'new-token')
            repeated_invalid = CountedClient([invalid, listing])
            self.assertEqual(execute(cfg, 'test', Path(tmp), repeated_invalid)['status'], 'error')
            self.assertEqual(repeated_invalid.attempts, 2)
            self.assertEqual((directory/'latest.json').read_bytes(), saved_snapshot)
            self.assertEqual(json.loads((directory/'property-resolution.json').read_text())['property_token'], 'new-token')

    def test_fallback_requires_explicit_token_error_and_enough_budget(self):
        invalid = SearchAPIError({'provider': 'searchapi.io', 'category': 'http_error',
            'http_status': 400, 'message': 'Invalid property_token',
            'request_parameters': {'engine': 'google_hotels_property'}})
        unsupported_locale = SearchAPIError({'provider': 'searchapi.io', 'category': 'http_error',
            'http_status': 400, 'message': 'Unsupported value in hl parameter',
            'request_parameters': {'engine': 'google_hotels_property'}})
        quota = SearchAPIError({'provider': 'searchapi.io', 'category': 'http_error',
            'http_status': 429, 'message': 'Invalid property_token',
            'request_parameters': {'engine': 'google_hotels_property'}})
        self.assertTrue(invalid_property_token_error(invalid))
        self.assertFalse(invalid_property_token_error(unsupported_locale))
        self.assertFalse(invalid_property_token_error(quota))
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'persistence_root': 'hotels', 'execution': {'query_enabled': True},
                   'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW'},
                   'monitors': [monitor('booked_room_compare')]}
            cfg['monitors'][0]['hotel_identity']['name'] = 'Hotel'
            directory = Path(tmp)/'hotels/test'
            directory.mkdir(parents=True)
            (directory/'latest.json').write_text('{"run_id":"old"}')
            (directory/'property-resolution.json').write_text(json.dumps({
                'schema_version': 2, 'monitor_id': 'test', 'provider': 'searchapi.io',
                'data_id': 'hotel1', 'hotel_name': 'Hotel', 'configured_hotel_name': 'Hotel',
                'property_token': 'old-token', 'evidence': {'source': 'searchapi.io/google_hotels',
                    'source_path': 'properties[0].property_token', 'observed_at': '2026-10-01T00:00:00+00:00'}}))
            for response, limit in ((unsupported_locale, 5), (quota, 5), (invalid, 2)):
                with self.subTest(message=response.diagnostics['message'], limit=limit):
                    client = CountedClient([response], limit=limit)
                    self.assertEqual(execute(cfg, 'test', Path(tmp), client)['status'], 'error')
                    self.assertEqual(client.attempts, 1)
                    self.assertEqual(json.loads((directory/'latest.json').read_text())['run_id'], 'old')
                    self.assertEqual(json.loads((directory/'property-resolution.json').read_text())['property_token'], 'old-token')

    def test_mismatched_monitor_or_property_fails_without_replacing_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'persistence_root': 'hotels', 'execution': {'query_enabled': True},
                   'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW'},
                   'monitors': [monitor('booked_room_compare')]}
            cfg['monitors'][0]['hotel_identity']['name'] = 'Hotel'
            directory = Path(tmp)/'hotels/test'
            directory.mkdir(parents=True)
            (directory/'latest.json').write_text('{"run_id":"old"}')
            cache = {'schema_version': 2, 'monitor_id': 'other-monitor', 'provider': 'searchapi.io',
                     'data_id': 'hotel1', 'hotel_name': 'Hotel', 'configured_hotel_name': 'Hotel',
                     'property_token': 'old-token', 'evidence': {'source': 'searchapi.io/google_hotels',
                         'source_path': 'properties[0].property_token', 'observed_at': '2026-10-01T00:00:00+00:00'}}
            (directory/'property-resolution.json').write_text(json.dumps(cache))
            client = CountedClient([])
            self.assertEqual(execute(cfg, 'test', Path(tmp), client)['status'], 'error')
            self.assertEqual(client.attempts, 0)
            cache['monitor_id'] = 'test'
            (directory/'property-resolution.json').write_text(json.dumps(cache))
            client = CountedClient([{'property': {'name': 'Other Hotel', 'data_id': 'other-id'}}])
            self.assertEqual(execute(cfg, 'test', Path(tmp), client)['status'], 'error')
            self.assertEqual(client.attempts, 1)
            self.assertEqual(json.loads((directory/'latest.json').read_text())['run_id'], 'old')
            self.assertEqual(json.loads((directory/'property-resolution.json').read_text())['property_token'], 'old-token')

    def test_cached_token_preserves_room_comparison_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'persistence_root': 'hotels', 'execution': {'query_enabled': True},
                   'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW'},
                   'monitors': [monitor('booked_room_compare')]}
            cfg['monitors'][0]['hotel_identity']['name'] = 'Hotel'
            directory = Path(tmp)/'hotels/test'
            directory.mkdir(parents=True)
            (directory/'property-resolution.json').write_text(json.dumps({
                'schema_version': 2, 'monitor_id': 'test', 'provider': 'searchapi.io',
                'data_id': 'hotel1', 'hotel_name': 'Hotel', 'configured_hotel_name': 'Hotel',
                'property_token': 'old-token', 'evidence': {'source': 'searchapi.io/google_hotels',
                    'source_path': 'properties[0].property_token', 'observed_at': '2026-10-01T00:00:00+00:00'}}))
            detail = {'property': {'name': 'Hotel', 'data_id': 'hotel1',
                'featured_offers': [{'source': 'Booking.com', 'rooms': [
                    {'name': 'Twin Room - Smoking',
                     'rates': [{'total_price': {'extracted_price': 60000}}]}
                ]}]}}
            result = execute(cfg, 'test', Path(tmp), CountedClient([detail]))
            self.assertEqual(result['attempted_requests'], 1)
            q = json.loads((directory/'latest.json').read_text())['observations'][0]
            self.assertEqual((q['room_match'], q['comparison_status']), ('mismatch', 'not_comparable'))
            self.assertIsNone(q['alert_reached'])
            self.assertIsNone(q['difference'])

    def test_success_empty_partial_disabled_and_paths(self):
        from unittest.mock import Mock
        cfg = {'persistence_root': 'hotels', 'execution': {'query_enabled': True, 'max_quote_age_hours': 1},
               'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW'}, 'monitors': [monitor()]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = Mock(attempts=1, limit=5)
            client.search.return_value = {'properties': []}
            self.assertEqual(execute(cfg, 'test', root, client)['status'], 'success')
            d = root/'hotels/test'
            self.assertEqual(json.loads((d/'latest.json').read_text())['observations'], [])
            before = (d/'latest.json').read_bytes(), (d/'history.csv').read_bytes()
            client.attempts = 5
            client.search.return_value = {'properties': [{'type': 'hotel', 'name': 'H', 'property_token': 'x'}]}
            self.assertEqual(execute(cfg, 'test', root, client)['status'], 'partial')
            self.assertEqual(before, ((d/'latest.json').read_bytes(), (d/'history.csv').read_bytes()))
            cfg['execution']['query_enabled'] = False
            client.reset_mock()
            self.assertEqual(execute(cfg, 'test', root, client)['status'], 'skipped')
            client.search.assert_not_called()
            with self.assertRaises(ValueError): report(cfg, '../escape', root)

    def test_history_append_and_unknown_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp); m = monitor(); q = quote(m)
            q = assess(m, q, 1, q['observed_at'])
            snap = dict(schema_version=1, monitor_id='test', stage=m['stage'], comparison_key='key', run_id='one', observations=[q])
            persist(d, snap, {'status': 'success'})
            text = (d/'history.csv').read_text()
            self.assertIn('snapshots/one.json#/observations/0', text)
            snap['run_id'] = 'two'
            persist(d, snap, {'status': 'success'})
            self.assertEqual(len((d/'history.csv').read_text().splitlines()), 3)
            self.assertTrue((d/'snapshots/one.json').exists())

    def test_stage1_unknown_and_fail(self):
        m = monitor()
        self.assertEqual(assess(m, {'source': 'OTA'}, 1, '2026-10-01T00:00:00+00:00')['filter_status'], 'pending_confirmation')
        q = quote(m)
        self.assertEqual(assess(m, q, 1, q['observed_at'])['filter_status'], 'qualified')
        q['evidence']['room_size_m2']['literal_value'] = 29
        self.assertEqual(assess(m, q, 1, q['observed_at'])['filter_status'], 'excluded')

    def test_stage2_evidence_and_threshold(self):
        m = monitor('booked_room_compare'); q = quote(m)
        r = assess(m, q, 1, q['observed_at'])
        self.assertEqual(r['room_match'], 'equivalent')
        self.assertTrue(r['alert_reached'])
        q['total_amount'] = 70000
        q['evidence']['total_amount']['literal_value'] = 70000
        self.assertFalse(assess(m, q, 1, q['observed_at'])['alert_reached'])
        del q['evidence']['beds']
        self.assertIsNone(assess(m, q, 1, q['observed_at'])['difference'])

    def test_stage2_caches_confirmed_token_and_uses_direct_property_next_run(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'persistence_root': 'hotels', 'execution': {'query_enabled': True, 'max_quote_age_hours': 1},
                   'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW'},
                   'monitors': [monitor('booked_room_compare')]}
            cfg['monitors'][0]['hotel_identity']['name'] = 'Hotel'
            listing = {'properties': [{'name': 'Hotel', 'type': 'hotel', 'data_id': 'hotel1', 'property_token': 'confirmed-token'}]}
            detail = {'property': {'name': 'Hotel', 'data_id': 'hotel1', 'featured_offers': []}}
            first = Mock(attempts=2, limit=5)
            first.search.side_effect = [listing, detail]
            self.assertEqual(execute(cfg, 'test', Path(tmp), first)['status'], 'success')
            resolution = json.loads((Path(tmp)/'hotels/test/property-resolution.json').read_text())
            self.assertEqual(resolution['data_id'], 'hotel1')
            self.assertEqual(resolution['property_token'], 'confirmed-token')
            second = Mock(attempts=1, limit=5)
            second.search.return_value = detail
            self.assertEqual(execute(cfg, 'test', Path(tmp), second)['status'], 'success')
            second.search.assert_called_once()
            params = second.search.call_args.args[0]
            self.assertEqual(params['engine'], 'google_hotels_property')
            self.assertEqual(params['property_token'], 'confirmed-token')
            self.assertNotIn('q', params)

    def test_changed_hotel_identity_protects_snapshot_and_resolution(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'persistence_root': 'hotels', 'execution': {'query_enabled': True},
                   'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW'},
                   'monitors': [monitor('booked_room_compare')]}
            cfg['monitors'][0]['hotel_identity']['name'] = 'Hotel'
            directory = Path(tmp)/'hotels/test'; directory.mkdir(parents=True)
            (directory/'latest.json').write_text('{"run_id":"old"}')
            (directory/'property-resolution.json').write_text(json.dumps({
                'provider': 'searchapi.io', 'data_id': 'hotel1', 'hotel_name': 'Hotel',
                'property_token': 'confirmed-token', 'schema_version': 1,
                'evidence': {'source': 'searchapi.io/google_hotels',
                             'source_path': 'properties[0].property_token',
                             'observed_at': '2026-10-01T00:00:00+00:00'}}))
            detail = {'property': {'name': 'Different Hotel', 'data_id': 'other-id'}}
            client = Mock(attempts=1, limit=5)
            client.search.return_value = detail
            self.assertEqual(execute(cfg, 'test', Path(tmp), client)['status'], 'error')
            self.assertEqual(json.loads((directory/'latest.json').read_text())['run_id'], 'old')
            self.assertEqual(json.loads((directory/'property-resolution.json').read_text())['data_id'], 'hotel1')
            cfg['monitors'][0]['hotel_identity']['source_ids']['searchapi.io'] = 'another-id'
            client.reset_mock()
            self.assertEqual(execute(cfg, 'test', Path(tmp), client)['status'], 'error')
            client.search.assert_not_called()

    def test_live_smoking_label_is_excluded_without_price_alert(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'persistence_root': 'hotels', 'execution': {'query_enabled': True, 'max_quote_age_hours': 1},
                   'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW'},
                   'monitors': [monitor('booked_room_compare')]}
            cfg['monitors'][0]['hotel_identity']['name'] = 'Hotel'
            client = Mock(attempts=2, limit=5)
            client.search.side_effect = [
                {'properties': [{'name': 'Hotel', 'type': 'hotel', 'data_id': 'hotel1', 'property_token': 'token'}]},
                {'property': {'name': 'Hotel', 'data_id': 'hotel1', 'featured_offers': [{'source': 'Booking.com',
                    'rooms': [{'name': 'Twin Room - Smoking', 'rates': [{'total_price': {'extracted_price': 76273}}]}]}]}}]
            self.assertEqual(execute(cfg, 'test', Path(tmp), client)['status'], 'success')
            q = json.loads((Path(tmp)/'hotels/test/latest.json').read_text())['observations'][0]
            self.assertEqual(q['field_status']['smoking'], 'fail')
            self.assertEqual(q['room_match'], 'mismatch')
            self.assertEqual(q['comparison_status'], 'not_comparable')
            self.assertIsNone(q['alert_reached'])
            self.assertEqual(q['evidence']['smoking']['derived_from'], 'room_name')

    def test_baseline_unknown_stale_mismatch(self):
        m = monitor('booked_room_compare'); q = quote(m)
        m['booking_baseline']['currency'] = None
        self.assertIsNone(assess(m, q, 1, q['observed_at'])['alert_reached'])
        m = monitor('booked_room_compare')
        self.assertIsNone(assess(m, q, 1, '2026-10-02T00:00:00+00:00')['difference'])
        q['evidence']['smoking']['literal_value'] = 'smoking'
        self.assertEqual(assess(m, q, 1, q['observed_at'])['room_match'], 'mismatch')

    def test_transaction_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp); snap = {'run_id': 'one', 'observations': []}
            persist(d, snap, {'status': 'success'})
            self.assertTrue((d/'snapshots/one.json').exists())
            self.assertEqual(json.loads((d/'latest.json').read_text())['run_id'], 'one')
            (d/'.transaction.json').write_text(json.dumps({'files': {'latest.json': json.dumps({'run_id': 'two'}), 'history.csv': 'two'}}))
            recover(d)
            self.assertEqual((d/'history.csv').read_text(), 'two')

    def test_interrupted_publication_recovers_without_duplicate_history(self):
        from unittest.mock import patch
        import hotel_executor
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp); real_atomic = hotel_executor.atomic
            def interrupt(path, text):
                if path.name == 'latest.json': raise OSError('disk interruption')
                real_atomic(path, text)
            snap = {'run_id': 'recoverable', 'observations': []}
            with patch('hotel_executor.atomic', side_effect=interrupt):
                with self.assertRaises(OSError): persist(d, snap, {'status': 'success'})
            self.assertTrue((d/'.transaction.json').exists())
            recover(d)
            before = (d/'history.csv').read_bytes()
            recover(d)
            self.assertEqual(before, (d/'history.csv').read_bytes())
            self.assertEqual(json.loads((d/'latest.json').read_text())['run_id'], 'recoverable')

    def test_real_parser_to_executor_chain_stays_uncertain(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'persistence_root': 'hotels', 'execution': {'query_enabled': True, 'max_quote_age_hours': 1},
                   'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW'}, 'monitors': [monitor('booked_room_compare')]}
            cfg['monitors'][0]['hotel_identity']['name'] = 'Hotel'
            client = Mock(attempts=2, limit=5)
            client.search.side_effect = [
                {'properties': [{'name': 'Hotel', 'type': 'hotel', 'data_id': 'hotel1', 'property_token': 'token'}]},
                {'property': {'name': 'Hotel', 'data_id': 'hotel1', 'featured_offers': [{'source': 'OTA',
                    'rooms': [{'name': 'Twin', 'total_price': {'extracted_price': 12345}}]}]}}]
            result = execute(cfg, 'test', Path(tmp), client)
            self.assertEqual(result['status'], 'success')
            latest = json.loads((Path(tmp)/'hotels/test/latest.json').read_text())
            q = latest['observations'][0]
            self.assertEqual(q['room_match'], 'uncertain')
            self.assertIsNone(q['alert_reached'])
            self.assertIsNone(q['difference'])
            self.assertNotIn('token', json.dumps(latest['observations']))
            self.assertEqual(latest['property_resolution']['property_token'], 'token')

    def test_exact_match_and_config_change(self):
        m = monitor('booked_room_compare'); q = quote(m)
        m['room_baseline']['source_id'] = 'room1'
        q['evidence']['room_identity'] = dict(q['evidence']['beds'], literal_value='room1')
        self.assertEqual(assess(m, q, 1, q['observed_at'])['room_match'], 'exact_match')
        del q['evidence']['beds']['source']
        self.assertEqual(assess(m, q, 1, q['observed_at'])['room_match'], 'uncertain')

    def test_api_failure_preserves_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'persistence_root': 'hotels', 'execution': {'query_enabled': True, 'max_quote_age_hours': 1},
                   'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW', 'max_verification_requests': 5}, 'monitors': [monitor()]}
            class Broken:
                attempts = 1
                def search(self, params): raise RuntimeError('secret')
            d = Path(tmp)/'hotels/test'; d.mkdir(parents=True)
            (d/'latest.json').write_text('{"run_id":"old"}')
            (d/'history.csv').write_text('old')
            r = execute(cfg, 'test', Path(tmp), Broken())
            self.assertEqual(r['status'], 'error')
            self.assertEqual((d/'history.csv').read_text(), 'old')
            self.assertEqual(json.loads((d/'latest.json').read_text())['run_id'], 'old')
            self.assertNotIn('secret', (d/'last-run.json').read_text())
            before = {p.name: p.read_bytes() for p in d.iterdir()}
            report(cfg, 'test', Path(tmp))
            self.assertEqual(before, {p.name: p.read_bytes() for p in d.iterdir()})


if __name__ == '__main__': unittest.main()
