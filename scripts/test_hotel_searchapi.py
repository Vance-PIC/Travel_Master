import unittest
from unittest.mock import Mock
from hotel_searchapi import Client, parameters, room_quotes, verify


class HotelTests(unittest.TestCase):
    def test_localization_is_injected_without_fallback(self):
        m = {'stay': {'check_in': '2027-07-11', 'check_out': '2027-07-17'},
             'party': {'adults': 2, 'children': 2, 'child_ages': [9, 7]}}
        p = parameters(m, 'TWD', 'ja', 'JP')
        self.assertEqual((p['currency'], p['hl'], p['gl']), ('TWD', 'ja', 'JP'))
        with self.assertRaises(ValueError): parameters(m, 'JPY', None, 'TW')

    def test_verification_stops_at_budget(self):
        import io
        import json
        listing = {'properties': [{'type': 'hotel', 'name': str(i), 'property_token': str(i)} for i in range(8)]}
        opener = Mock(side_effect=[io.StringIO(json.dumps(listing))] + [io.StringIO('{"property": {}}') for _ in range(4)])
        client = Client('test', 5, opener)
        config = {'api': {'query_currency': 'JPY', 'hl': 'en-US', 'gl': 'TW'}, 'monitors': [{'monitor_id': 'test',
                  'stage': 'candidate_search', 'stay': {'check_in': '2027-07-17', 'check_out': '2027-07-18'},
                  'party': {'adults': 2, 'children': 2, 'child_ages': [9, 7]},
                  'hard_filters': {'location': {'anchor': 'airport'}}}]}
        report = verify(config, 'test', client)
        self.assertEqual(opener.call_count, 5)
        self.assertEqual(report['alerts'], [])
        self.assertNotIn('property_token', json.dumps(report))

    def test_children_are_explicit(self):
        m = {'stay': {'check_in': '2027-07-11', 'check_out': '2027-07-17'},
             'party': {'adults': 2, 'children': 2, 'child_ages': [9, 7]}}
        self.assertEqual(parameters(m, 'JPY', 'en-US', 'TW')['children_ages'], '9,7')
        m['party']['child_ages'] = None
        with self.assertRaises(ValueError):
            parameters(m, 'JPY', 'en-US', 'TW')

    def test_aggregate_is_never_a_room_quote(self):
        self.assertEqual(room_quotes({'property': {'total_price': {'extracted_price': 1},
                        'featured_offers': [{'source': 'OTA', 'total_price': {'extracted_price': 1}}]}}, 'JPY'), [])

    def test_no_parent_price_or_policy_inheritance(self):
        data = {'property': {'name': 'Hotel', 'featured_offers': [{'source': 'OTA',
                'total_price': {'extracted_price': 1}, 'has_free_cancellation': True,
                'rooms': [{'name': 'Twin', 'price_per_night': {'extracted_price': 10}}]}]}}
        q = room_quotes(data, 'JPY')[0]
        self.assertIsNone(q['total_amount'])
        self.assertIsNone(q['cancellation'])
        self.assertFalse(q['alert_eligible'])

    def test_failed_attempt_counts_and_no_secret_errors(self):
        opener = Mock(side_effect=OSError('secret-value'))
        client = Client('secret-value', 1, opener)
        with self.assertRaisesRegex(RuntimeError, '^SearchAPI request failed$'):
            client.search({'engine': 'google_hotels'})
        with self.assertRaisesRegex(RuntimeError, 'budget'):
            client.search({'engine': 'google_hotels'})
        self.assertEqual(opener.call_count, 1)
        request = opener.call_args.args[0]
        self.assertNotIn('secret-value', request.full_url)
        self.assertEqual(request.get_header('Authorization'), 'Bearer secret-value')


if __name__ == '__main__':
    unittest.main()
