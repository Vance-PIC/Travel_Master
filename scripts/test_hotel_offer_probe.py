import unittest

from hotel_offer_probe import summarize


class OfferProbeTests(unittest.TestCase):
    def test_counts_offer_only_sources_without_treating_them_as_room_quotes(self):
        monitor = {'monitor_id': 'marunouchi-booked',
                   'hotel_identity': {'name': 'Hotel', 'source_ids': {'searchapi.io': 'hotel1'}}}
        response = {'property': {'name': 'Hotel', 'data_id': 'hotel1',
            'featured_offers': [{'source': 'Hotels.com', 'total_price': {'extracted_price': 10000}}],
            'all_offers': [{'source': 'Booking.com', 'rooms': [{'name': 'Twin',
                'rates': [{'total_price': {'extracted_price': 9000}}]}]}]}}
        result = summarize(response, monitor, 'secret-key', '2026-12-11', '2026-12-12', 'JPY', 1)
        self.assertEqual(result['offer_count'], 2)
        self.assertEqual(result['saved_by_current_room_parser'], 1)
        self.assertEqual(result['parsed_sources'], ['Booking.com'])
        self.assertEqual(result['offers'][0]['source'], 'Hotels.com')
        self.assertEqual(result['offers'][0]['room_count'], 0)
        self.assertEqual(result['offers'][0]['offer_level_total_amount'], 10000)
        self.assertNotIn('secret-key', str(result))

    def test_rejects_wrong_hotel(self):
        monitor = {'monitor_id': 'marunouchi-booked',
                   'hotel_identity': {'name': 'Hotel', 'source_ids': {'searchapi.io': 'hotel1'}}}
        with self.assertRaises(ValueError):
            summarize({'property': {'name': 'Other Hotel', 'data_id': 'other'}},
                      monitor, 'secret-key', '2026-12-11', '2026-12-12', 'JPY', 1)


if __name__ == '__main__':
    unittest.main()
