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
    if type(value) is int:
        return value >= 0
    return type(value) is float and math.isfinite(value) and value >= 0


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


def cell(value: object) -> str:
    """Escape every snapshot-derived value as text, never markup."""
    from html import escape
    return escape(str(value if value is not None else '—'), quote=True)


def render_page(flights: list[dict], hotels: list[dict], status: dict) -> str:
    """Render explicit public columns; unknown keys never enter the document."""
    def rows(items, fields):
        result = []
        for item in items:
            values = [cell(item.get(field)) for field in fields]
            values.append('資料過期' if item.get('stale') is True else '48 小時內')
            result.append('<tr>' + ''.join('<td>' + value + '</td>' for value in values) + '</tr>')
        return ''.join(result) or '<tr><td colspan="' + str(len(fields) + 1) + '">無可用報價</td></tr>'

    flight_fields = ('origin', 'destination', 'outbound_date', 'inbound_date', 'airline',
                     'outbound_flight', 'outbound_departure', 'outbound_arrival',
                     'inbound_flight', 'inbound_departure', 'inbound_arrival',
                     'displayed_price_twd', 'price_label', 'checked_at')
    hotel_fields = ('hotel_name', 'check_in', 'check_out', 'total_amount', 'query_currency',
                    'nightly_amount', 'source', 'verification_status', 'comparison_status', 'observed_at')
    allowed = {'正常', '無可用報價', '資料無法讀取', '無有效觀測'}
    messages = []
    for key, label in (('flights', '機票'), ('hotels', '飯店')):
        values = status.get(key, [])
        if not isinstance(values, list):
            values = []
        messages.append(label + '：' + '、'.join(cell(value) for value in values if value in allowed))
    for items, label, time_field in ((flights, '機票', 'checked_at'), (hotels, '飯店', 'observed_at')):
        times = [item.get(time_field) for item in items if _timestamp(item.get(time_field))]
        if times:
            latest = max(times, key=_timestamp)
            messages.append(label + '最新有效觀測：' + cell(latest))
        if any(item.get('stale') is True for item in items):
            messages.append(label + '：資料過期')
    if any(item.get('price_scope') != 'family_total' for item in flights):
        messages.append('機票價格範圍未驗證；行李狀態未知')
    template = (Path(__file__).resolve().parents[1] / 'site/public_price_template.html').read_text(encoding='utf-8')
    replacements = {'{{FLIGHT_ROWS}}': rows(flights, flight_fields),
                    '{{HOTEL_ROWS}}': rows(hotels, hotel_fields),
                    '{{STATUS}}': '<br>'.join(messages)}
    # Replace template tokens in one pass so data containing tokens stays literal.
    import re
    return re.sub(r'\{\{(?:FLIGHT_ROWS|HOTEL_ROWS|STATUS)\}\}',
                  lambda match: replacements[match.group()], template)


def build_page(root: Path, now: datetime) -> str:
    """Read local sources without exposing paths, errors, or raw snapshot contents."""
    base = Path(root) / 'travel/nagoya'
    snapshot, flight_status = read_snapshot(base / 'flights/latest.json')
    flights = project_flights(snapshot, now)
    if flight_status == '正常' and not flights:
        flight_status = '無有效觀測'
    hotel_dir = base / 'hotels'
    hotels = project_hotels(hotel_dir, now)
    hotel_statuses = []
    # Monitor directories may exist even when their latest snapshot is missing.
    for directory in sorted(hotel_dir.iterdir()) if hotel_dir.is_dir() else []:
        if not directory.is_dir():
            continue
        snapshot, value = read_snapshot(directory / 'latest.json')
        if value == '正常' and not _has_hotel_observations(snapshot):
            value = '無有效觀測'
        hotel_statuses.append(value)
    return render_page(flights, hotels, {'flights': [flight_status],
                                        'hotels': hotel_statuses or ['無可用報價']})


def _has_hotel_observations(snapshot: dict) -> bool:
    observations = snapshot.get('observations')
    if not isinstance(observations, list):
        return False
    return any(isinstance(item, dict)
            and _valid_price(item.get('total_amount')) and _timestamp(item.get('observed_at'))
            and isinstance(item.get('query_currency'), str) and item['query_currency']
               for item in observations)


def main() -> None:
    import argparse
    from datetime import timezone
    parser = argparse.ArgumentParser(description='Build the public local-snapshot price page.')
    parser.add_argument('--output', type=Path, default=Path('_site'))
    args = parser.parse_args()
    page = build_page(Path(__file__).resolve().parents[1], datetime.now(timezone.utc))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'index.html').write_text(page, encoding='utf-8')


if __name__ == '__main__':
    main()
