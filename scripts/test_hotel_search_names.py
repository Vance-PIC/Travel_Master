import unittest
from unittest.mock import Mock
from hotel_executor import collect
from test_hotel_executor import monitor


class SearchNameTests(unittest.TestCase):
    def test_pagination_only_blocks_candidate_search(self):
        for stage in ('booked_room_compare', 'candidate_search'):
            with self.subTest(stage=stage):
                m = monitor(stage)
                m['hotel_identity'] = {'name': 'Hotel', 'source_ids': {}}
                m['search'] = {'query': 'Hotels'}
                client = Mock(attempts=2, limit=5)
                client.search.side_effect = [
                    {'properties': [{'type': 'hotel', 'name': 'Hotel', 'data_id': 'id', 'property_token': 'token'}],
                     'pagination': {'next_page_token': 'next'}},
                    {'property': {'name': 'Hotel', 'data_id': 'id'}}]
                _, coverage = collect({'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW'}}, m, client)
                self.assertEqual(coverage['completed'], ['id'])
                self.assertEqual(coverage['deferred'], ['additional_results_page'] if stage == 'candidate_search' else [])

    def test_confirmed_property_token_skips_discovery(self):
        m = monitor('booked_room_compare')
        m['hotel_identity']['name'] = 'Hotel'
        m['search'] = {'property_token': 'ChConfirmed', 'property_token_evidence': {'source': 'searchapi.io', 'reference': 'confirmed response'}}
        client = Mock(attempts=1, limit=5)
        client.search.return_value = {'property': {'name': 'Hotel', 'data_id': 'hotel1'}}
        collect({'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW', 'engine_parameters': {'google_hotels_property': {'hl': None}}}}, m, client)
        client.search.assert_called_once()
        params = client.search.call_args.args[0]
        self.assertEqual(params['engine'], 'google_hotels_property')
        self.assertEqual(params['property_token'], 'ChConfirmed')
        self.assertNotIn('q', params)
        self.assertNotIn('hl', params)
        m['search']['property_token'] = '/g/kgmid'
        with self.assertRaises(ValueError):
            collect({'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW', 'engine_parameters': {'google_hotels_property': {'hl': None}}}}, m, client)

    def test_query_alias_preserves_exact_party_dates_and_currency(self):
        m = monitor('booked_room_compare')
        m['hotel_identity'] = {'name': 'Hotel LiVEMAX PREMIUM Nagoya Marunouchi', 'source_ids': {},
                               'discovery_aliases': ['Hotel Live Max PREMIUM Nagoya Marunouchi']}
        m['search'] = {'query': 'Hotel Live Max PREMIUM Nagoya Marunouchi'}
        client = Mock(attempts=2, limit=5)
        client.search.side_effect = [{'properties': [
            {'type': 'hotel', 'name': 'Hotel Live Max PREMIUM Nagoya Marunouchi', 'data_id': 'id', 'property_token': 'token'},
            {'type': 'hotel', 'name': 'Hotel Live Max Nagoya OTHER', 'property_token': 'wrong'}]},
            {'property': {'name': 'Hotel Live Max PREMIUM Nagoya Marunouchi', 'data_id': 'id'}}]
        rows, coverage = collect({'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW', 'engine_parameters': {'google_hotels_property': {'hl': None}}}}, m, client)
        self.assertEqual(client.search.call_count, 2)
        first = client.search.call_args_list[0].args[0]
        self.assertEqual(first['q'], m['search']['query'])
        for call in client.search.call_args_list:
            p = call.args[0]
            self.assertEqual(p['children_ages'], '9,7')
            self.assertEqual(p['adults'], 2)
            self.assertEqual(p['check_in_date'], '2027-07-11')
            self.assertEqual(p['check_out_date'], '2027-07-17')
            self.assertEqual(p['currency'], 'JPY')
            if p['engine'] == 'google_hotels':
                self.assertEqual(p['hl'], 'en')
            else:
                self.assertNotIn('hl', p)
            self.assertEqual(p['gl'], 'TW')
        self.assertEqual(coverage['completed'], ['id'])
        self.assertEqual(rows, [])


if __name__ == '__main__': unittest.main()
