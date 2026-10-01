"""Bounded SearchAPI hotel capability verification; no alerts or monitor snapshots."""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import urllib.parse
import urllib.request
import urllib.error

ENDPOINT = 'https://www.searchapi.io/api/v1/search'


class SearchAPIError(RuntimeError):
    def __init__(self, diagnostics):
        super().__init__('SearchAPI request failed')
        self.diagnostics = diagnostics


def safe_text(value, key):
    if not isinstance(value, str): return None
    text = value
    # Decode escaped credentials before redaction; never retain raw response.
    for _ in range(3): text = urllib.parse.unquote(text)
    secrets = [key] + [v for k, v in os.environ.items()
                       if re.search(r'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH', k, re.I) and v]
    variants = set()
    for secret in secrets:
        if secret:
            variants.update((secret, base64.b64encode(secret.encode()).decode(),
                             json.dumps(secret)[1:-1]))
    for secret in sorted(variants, key=len, reverse=True): text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'https?://\S+', '[URL REDACTED]', text, flags=re.I)
    text = re.sub(r'Authorization[\"\x27]?\s*[:=][^\r\n]*', '[HEADER REDACTED]', text, flags=re.I)
    text = re.sub(r'\bBearer\s+\S+', '[CREDENTIAL REDACTED]', text, flags=re.I)
    text = re.sub(r'\b(?:[\w-]*(?:api[_-]?key|token|secret|password|credential))[\"\x27]?\s*[:=]\s*(?:\"[^\"]*\"|\x27[^\x27]*\x27|[^\s,;]+)', '[CREDENTIAL REDACTED]', text, flags=re.I)
    return re.sub(r'[\x00-\x1f\x7f]', ' ', text)[:500]


def diagnostics(category, status, data, key):
    result = {'provider': 'searchapi.io', 'category': category, 'http_status': status}
    if isinstance(data, dict):
        error = data.get('error') or data.get('errors')
        if isinstance(error, list): error = error[0] if error else None
        if isinstance(error, dict):
            typ = error.get('type') or error.get('code')
            message = error.get('message')
        else:
            typ = data.get('error_type') or data.get('type')
            message = error if isinstance(error, str) else data.get('message')
        for field, value in (('error_type', typ), ('message', message)):
            cleaned = safe_text(value, key)
            if cleaned: result[field] = cleaned
    return result


class Client:
    def __init__(self, key, max_requests=5, opener=urllib.request.urlopen):
        if not key or not 1 <= max_requests <= 5:
            raise ValueError('Key required; request budget must be 1–5')
        self.key, self.limit, self.opener, self.attempts = key, max_requests, opener, 0

    def search(self, params):
        if params.get('engine') not in ('google_hotels', 'google_hotels_property'):
            raise ValueError('Unsupported hotel engine')
        if 'api_key' in params:
            raise ValueError('Use header authentication')
        if self.attempts >= self.limit:
            raise RuntimeError('SearchAPI request budget exhausted')
        self.attempts += 1
        request = urllib.request.Request(ENDPOINT + '?' + urllib.parse.urlencode(params),
                                        headers={'Authorization': 'Bearer ' + self.key})
        status = None
        try:
            with self.opener(request, timeout=60) as response:
                status = getattr(response, 'status', None)
                data = json.load(response)
            if not isinstance(data, dict) or data.get('error') or data.get('errors'):
                raise SearchAPIError(diagnostics('api_error', status, data, self.key))
            return data
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read(65536))
            except Exception:
                data = None
            raise SearchAPIError(diagnostics('http_error', exc.code, data, self.key)) from None
        except SearchAPIError:
            raise
        except (ValueError, UnicodeError):
            raise SearchAPIError(diagnostics('invalid_json', status, None, self.key)) from None
        except Exception:
            # Never expose URLs, headers or upstream bodies in logs. No retry.
            raise SearchAPIError(diagnostics('transport_error', None, None, self.key)) from None


def parameters(monitor, currency):
    party = monitor['party']
    ages = party.get('child_ages')
    if not isinstance(ages, list) or len(ages) != party['children']:
        raise ValueError('Confirmed child ages required')
    if any(type(age) is not int or not 1 <= age <= 17 for age in ages):
        raise ValueError('Child age outside supported range')
    stay = monitor['stay']
    if datetime.fromisoformat(stay['check_out']) <= datetime.fromisoformat(stay['check_in']):
        raise ValueError('Invalid stay dates')
    return {'check_in_date': stay['check_in'], 'check_out_date': stay['check_out'],
            'adults': party['adults'], 'children_ages': ','.join(map(str, ages)),
            'currency': currency, 'hl': 'en', 'gl': 'tw'}


def room_quotes(data, currency):
    """Only room/rate-level values; do not inherit hotel or OTA aggregate prices."""
    prop = data.get('property', {})
    result = []
    for group in ('featured_offers', 'all_offers'):
        for oi, offer in enumerate(prop.get(group, [])):
            for ri, room in enumerate(offer.get('rooms', [])):
                for ti, rate in enumerate(room.get('rates') or [room]):
                    result.append({
                        'hotel_name': prop.get('name'), 'hotel_data_id': prop.get('data_id'),
                        'source': offer.get('source'), 'room_name': room.get('name'),
                        'evidence_path': f'property.{group}[{oi}].rooms[{ri}].rates[{ti}]' if room.get('rates') else f'property.{group}[{oi}].rooms[{ri}]',
                        'total_amount': rate.get('total_price', {}).get('extracted_price'),
                        'nightly_amount': rate.get('price_per_night', {}).get('extracted_price'),
                        'query_currency': currency, 'price_scope': 'unknown',
                        'reported_num_guests': rate.get('num_guests'),
                        'room_size_m2': None, 'beds': None, 'smoking': None,
                        'cancellation': rate.get('has_free_cancellation'),
                        'payment': None, 'benefits': None, 'tax_fee_inclusion': 'unknown',
                        'room_match': 'uncertain', 'comparison_status': 'pending_confirmation',
                        'alert_eligible': False})
    return result


def verify(config, monitor_id, client):
    m = next(m for m in config['monitors'] if m['monitor_id'] == monitor_id)
    p = parameters(m, config['api']['query_currency'])
    query = m['hotel_identity']['name'] if m['stage'] == 'booked_room_compare' else m['hard_filters']['location']['anchor'] + ' hotels'
    listing = client.search(dict(p, engine='google_hotels', q=query, property_type='hotel'))
    properties = listing.get('properties', [])
    if m['stage'] == 'booked_room_compare':
        # Name equality is discovery only, never proof of hotel/room equivalence.
        properties = [h for h in properties if h.get('name', '').casefold() == query.casefold()]
    rows = []
    discovered = [{'name': h.get('name'), 'data_id': h.get('data_id')} for h in properties]
    for hotel in properties:
        if client.attempts >= client.limit:
            break
        if hotel.get('type') != 'hotel' or not hotel.get('property_token'):
            continue
        detail = client.search(dict(p, engine='google_hotels_property', property_token=hotel['property_token']))
        rows.extend(room_quotes(detail, p['currency']))
    return {'mode': 'capability_verification', 'monitor_id': monitor_id, 'stage': m['stage'],
            'observed_at': datetime.now(timezone.utc).isoformat(), 'query': p,
            'attempted_requests': client.attempts, 'discovered_hotels': discovered,
            'room_quotes': rows, 'alerts': [],
            'limitations': ['Hotel identity requires source ID/address confirmation',
                            'Query party does not prove room occupancy or room count',
                            'Area, beds, smoking and rate policies require evidence',
                            'Baseline currency and price scope remain unconfirmed'],
            'status': 'response_received_unverified' if discovered else 'no_identity_match'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='travel/nagoya/hotel-monitor.json')
    parser.add_argument('--monitor', default='marunouchi-booked')
    parser.add_argument('--output', required=True)
    parser.add_argument('--live', action='store_true', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    output = Path(args.output)
    persistence = Path(config['persistence_root']).resolve()
    if output.resolve().is_relative_to(persistence):
        raise ValueError('Verification output cannot use monitor persistence')
    client = Client(os.environ.get('SEARCHAPI_KEY'), config['api']['max_verification_requests'])
    try:
        report = verify(config, args.monitor, client)
    except RuntimeError as exc:
        report = {'mode': 'capability_verification', 'status': 'failed',
                  'attempted_requests': client.attempts, 'error': str(exc)}
        if isinstance(exc, SearchAPIError): report['error_diagnostics'] = exc.diagnostics
    # Verification artifacts must never overwrite operational persistence.
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(report['status'])
    return 1 if report['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
