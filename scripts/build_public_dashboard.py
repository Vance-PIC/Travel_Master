"""Read local quote snapshots and project only fields approved for publication."""
import json
import math
from datetime import datetime, timedelta
from pathlib import Path


def read_snapshot(path: Path) -> tuple[dict, str]:
    """Return a snapshot and a short public status without exposing error details."""
    try:
        snapshot = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(snapshot, dict):
            return {}, '資料無法讀取'
        return snapshot, '正常'
    except FileNotFoundError:
        return {}, '無可用報價'
    except (OSError, ValueError):
        return {}, '資料無法讀取'


def _valid_price(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.utcoffset() is not None else None
    except ValueError:
        return None


def _text_fields(source, fields):
    return {field: source[field] for field in fields if isinstance(source.get(field), str)}


def project_flights(snapshot: dict, now: datetime) -> list[dict]:
    """Project the cheapest five itinerary quotes, retaining their observation time."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('itineraries'), list):
        return []
    route = snapshot.get('route')
    route = route if isinstance(route, dict) else {}
    rows = []
    for itinerary in snapshot['itineraries']:
        if not isinstance(itinerary, dict):
            continue
        price = itinerary.get('displayed_price_twd')
        checked = _timestamp(itinerary.get('checked_at'))
        if not _valid_price(price) or checked is None:
            continue
        verification = itinerary.get('price_verification')
        verification = verification if isinstance(verification, dict) else {}
        verified = (itinerary.get('price_scope') == 'family_total'
                    and _valid_price(itinerary.get('family_total_twd'))
                    and itinerary['family_total_twd'] == price
                    and verification.get('quote_checked_at') == itinerary['checked_at']
                    and _timestamp(verification.get('verified_at')) is not None
                    and _valid_price(verification.get('price'))
                    and verification['price'] == price)
        row = _text_fields(itinerary, ('airline', 'airline_iata', 'inbound_airline_iata',
                                      'outbound_flight', 'inbound_flight', 'outbound_departure',
                                      'outbound_arrival', 'inbound_departure', 'inbound_arrival'))
        row.update(_text_fields(route, ('origin', 'destination', 'outbound_date', 'inbound_date')))
        row.update(displayed_price_twd=price, checked_at=itinerary['checked_at'],
                   price_scope='family_total' if verified else 'unknown',
                   price_label='已驗證家庭總價' if verified else 'API 顯示價格，未驗證為家庭總價',
                   baggage_status='unknown', stale=now - checked > timedelta(hours=48))
        rows.append(row)
    return sorted(rows, key=lambda row: row['displayed_price_twd'])[:5]


def project_hotels(hotel_dir: Path, now: datetime) -> list[dict]:
    """Project hotel observations without baseline, party data, or currency conversion."""
    rows = []
    for path in sorted(Path(hotel_dir).glob('*/latest.json')):
        snapshot, _ = read_snapshot(path)
        observations = snapshot.get('observations')
        if not isinstance(observations, list):
            continue
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            amount = observation.get('total_amount')
            observed = _timestamp(observation.get('observed_at'))
            currency = observation.get('query_currency')
            if not _valid_price(amount) or observed is None or not isinstance(currency, str) or not currency:
                continue
            row = _text_fields(observation, ('hotel_name', 'source', 'query_currency',
                                             'observed_at', 'comparison_status', 'verification_status'))
            stay = observation.get('stay')
            if isinstance(stay, dict):
                row.update(_text_fields(stay, ('check_in', 'check_out')))
            row.update(total_amount=amount, stale=now - observed > timedelta(hours=48))
            if _valid_price(observation.get('nightly_amount')):
                row['nightly_amount'] = observation['nightly_amount']
            rows.append(row)
    return rows
