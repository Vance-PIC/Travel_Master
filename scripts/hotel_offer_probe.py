"""One-off, read-only SearchAPI offer-shape diagnostic for an alternate stay."""
import argparse
from datetime import date
import json
import os
from pathlib import Path

from hotel_executor import ROOT, location, normalized_name, trusted_resolution
from hotel_searchapi import Client, SearchAPIError, engine_parameters, parameters, room_quotes, safe_text


def summarize(data, monitor, key, check_in, check_out, currency, request_count):
    prop = data.get('property')
    if not isinstance(prop, dict):
        raise ValueError('Missing property object')
    names = [monitor['hotel_identity']['name']] + monitor['hotel_identity'].get('discovery_aliases', [])
    source_id = monitor['hotel_identity']['source_ids']['searchapi.io']
    if (prop.get('data_id') != source_id or
            normalized_name(prop.get('name')) not in {normalized_name(name) for name in names}):
        raise ValueError('Property identity conflicts with monitor')
    offers = []
    for group in ('featured_offers', 'all_offers'):
        group_items = prop.get(group, [])
        if not isinstance(group_items, list):
            raise ValueError('Malformed offer group')
        for index, offer in enumerate(group_items):
            if not isinstance(offer, dict):
                raise ValueError('Malformed offer')
            rooms = offer.get('rooms') or []
            if not isinstance(rooms, list):
                raise ValueError('Malformed room group')
            total = offer.get('total_price')
            amount = total.get('extracted_price') if isinstance(total, dict) else None
            offers.append({'group': group, 'index': index,
                           'source': safe_text(offer.get('source'), key),
                           'offer_level_total_amount': amount if type(amount) in (int, float) else None,
                           'room_count': len(rooms),
                           'room_rate_count': sum(len(room.get('rates') or [room])
                                                  for room in rooms if isinstance(room, dict))})
    parsed = room_quotes(data, currency)
    return {'monitor_id': monitor['monitor_id'], 'check_in': check_in, 'check_out': check_out,
            'hotel_data_id': source_id, 'query_currency': currency, 'request_count': request_count,
            'offer_count': len(offers), 'offers': offers,
            'saved_by_current_room_parser': len(parsed),
            'parsed_sources': sorted({safe_text(q['source'], key) for q in parsed if q.get('source')})}


def probe(check_in, check_out, config_path=ROOT/'travel/nagoya/hotel-monitor.json', client=None):
    if date.fromisoformat(check_out) <= date.fromisoformat(check_in):
        raise ValueError('Invalid stay')
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    monitor = next(m for m in config['monitors'] if m['monitor_id'] == 'marunouchi-booked')
    resolution = trusted_resolution(location(config, monitor['monitor_id'], ROOT), monitor)
    if not resolution:
        raise ValueError('Trusted property token required')
    query = dict(monitor, stay={'check_in': check_in, 'check_out': check_out})
    params = parameters(query, config['api']['query_currency'], config['api']['hl'], config['api']['gl'])
    key = os.environ.get(config['api']['key_env'])
    client = client or Client(key, 1)
    data = client.search(dict(engine_parameters(params, config['api'], 'google_hotels_property'),
                              engine='google_hotels_property', property_token=resolution['property_token']))
    prop = data.get('property')
    if isinstance(prop, dict) and prop.get('property_token') and prop['property_token'] != resolution['property_token']:
        raise ValueError('Property token conflicts with trusted resolution')
    return summarize(data, monitor, key, check_in, check_out,
                     config['api']['query_currency'], client.attempts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-in', required=True)
    parser.add_argument('--check-out', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        result = probe(args.check_in, args.check_out)
    except SearchAPIError as error:
        result = {'status': 'error', 'error_diagnostics': error.diagnostics}
    except (ValueError, KeyError, TypeError):
        result = {'status': 'error', 'error': 'Hotel diagnostic or identity validation failed'}
    else:
        result['status'] = 'success'
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
