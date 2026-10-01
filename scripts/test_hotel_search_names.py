import unittest
from unittest.mock import Mock
from hotel_executor import collect
from test_hotel_executor import monitor


class SearchNameTests(unittest.TestCase):
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
        rows, coverage = collect({'api': {'query_currency': 'JPY'}}, m, client)
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
        self.assertEqual(coverage['completed'], ['id'])
        self.assertEqual(rows, [])


if __name__ == '__main__': unittest.main()
