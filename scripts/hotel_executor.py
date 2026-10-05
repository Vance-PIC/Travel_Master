"""Hotel monitor executor. Search, persistence and read-only report are separate."""
import argparse
import copy
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import uuid
import tempfile
from datetime import datetime, timezone
from hotel_searchapi import Client, SearchAPIError, parameters, room_quotes, engine_parameters
from hotel_request import resolve_request, config_hash

ROOT = Path(__file__).resolve().parents[1]
FIELDS = 'schema_version run_id monitor_id stage comparison_key observed_at source hotel_key room_key rate_key status amount currency price_scope tax_fee_inclusion filter_status room_match comparison_status evidence_ref'.split()


def now(): return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def evidence(q, field):
    e = q.get('evidence', {}).get(field, {})
    if not e.get('source') or not (e.get('repo_path') or e.get('safe_url')) or not e.get('observed_at'):
        return None
    return e.get('literal_value')


def equal(actual, expected):
    if actual is None or expected is None or expected == 'unknown': return 'unknown'
    return 'pass' if actual == expected else 'fail'


def assess(m, quote, max_age, at):
    q = dict(quote)
    tests = {k: equal(evidence(q, k), m[k]) for k in ('stay', 'party')}
    tests['availability'] = equal(evidence(q, 'availability'), True)
    stage = m['stage']
    requirements = m['hard_filters'] if stage == 'candidate_search' else m['room_baseline']
    size = evidence(q, 'room_size_m2')
    target = requirements.get('min_room_size_m2') if stage == 'candidate_search' else requirements.get('size_m2')
    tests['room_size_m2'] = ('unknown' if not positive(size) or not positive(target) else
                             'pass' if (size >= target if stage == 'candidate_search' else size == target) else 'fail')
    beds = requirements.get('beds', {})
    for key in ('count', 'type'):
        actual = evidence(q, 'beds')
        tests['beds.'+key] = equal(actual.get(key) if isinstance(actual, dict) else None, beds.get(key))
        if stage == 'candidate_search' and beds.get(key) is None:
            tests.pop('beds.'+key)
    tests['smoking'] = equal(evidence(q, 'smoking'), requirements.get('smoking'))
    if stage == 'candidate_search':
        tests['location'] = equal(evidence(q, 'location'), True)
        ceiling = requirements.get('price_ceiling')
        if ceiling is not None:
            # Ceiling must specify its own currency/scope, never infer either.
            tests['price_ceiling'] = 'unknown'
            if isinstance(ceiling, dict) and positive(q.get('total_amount')):
                if all(equal(evidence(q, k), ceiling.get(k)) == 'pass' for k in ('currency', 'price_scope')) and positive(ceiling.get('amount')):
                    tests['price_ceiling'] = 'pass' if q['total_amount'] <= ceiling['amount'] else 'fail'
        for field in requirements:
            if field not in ('min_room_size_m2', 'beds', 'smoking', 'location', 'occupancy', 'price_ceiling'):
                tests[field] = 'unknown'
    else:
        identity = m['hotel_identity'].get('source_ids', {}).get('searchapi.io')
        tests['hotel_identity'] = equal(evidence(q, 'hotel_data_id'), identity)
    status = 'excluded' if 'fail' in tests.values() else 'qualified' if all(v == 'pass' for v in tests.values()) else 'pending_confirmation'
    q.update(field_status=tests, filter_status=status, fresh=True, retained=False,
             difference=None, alert_reached=None, comparison_status='pending_confirmation')
    if stage == 'candidate_search':
        q['room_match'] = None
        return q
    q['room_match'] = 'mismatch' if status == 'excluded' else 'uncertain' if status != 'qualified' else (
        'exact_match' if evidence(q, 'room_identity') == m['room_baseline'].get('source_id') and evidence(q, 'room_identity') is not None else 'equivalent')
    base = m['booking_baseline']
    checks = {k: equal(evidence(q, k), base.get(k)) for k in ('currency', 'price_scope', 'tax_fee_inclusion', 'cancellation', 'payment', 'benefits')}
    checks['scope'] = equal(evidence(q, 'price_scope'), 'total_stay_all_rooms_party')
    checks['eligibility'] = equal(evidence(q, 'eligibility'), True)
    checks['baseline_source'] = 'pass' if base.get('source') else 'unknown'
    checks['amount'] = 'pass' if positive(q.get('total_amount')) and positive(base.get('amount')) else 'unknown'
    checks['amount_evidence'] = equal(evidence(q, 'total_amount'), q.get('total_amount'))
    try:
        age = (datetime.fromisoformat(at) - datetime.fromisoformat(q['observed_at'])).total_seconds()/3600
        checks['freshness'] = 'pass' if positive(max_age) and 0 <= age <= max_age else 'unknown'
    except (KeyError, TypeError, ValueError): checks['freshness'] = 'unknown'
    q['comparison_checks'] = checks
    if q['room_match'] == 'mismatch' or 'fail' in checks.values():
        q['comparison_status'] = 'not_comparable'
    elif q['room_match'] in ('exact_match', 'equivalent') and all(v == 'pass' for v in checks.values()):
        q['comparison_status'] = 'comparable'
        q['difference'] = q['total_amount'] - base['amount']
        alert = m['alert']
        if positive(alert.get('amount')) and all(equal(alert.get(k), base.get(k)) == 'pass' for k in ('currency', 'price_scope')):
            q['alert_reached'] = q['difference'] < 0 and q['total_amount'] < alert['amount']
    return q


def atomic(path, text):
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8', newline='') as f:
        f.write(text); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def recover(directory):
    journal = directory/'.transaction.json'
    if journal.exists():
        files = json.loads(journal.read_text(encoding='utf-8'))['files']
        for name, content in files.items():
            dest = (directory/name).resolve()
            if not dest.is_relative_to(directory.resolve()): raise ValueError('Invalid transaction path')
            dest.parent.mkdir(parents=True, exist_ok=True)
            atomic(dest, content)
        journal.unlink()


def persist(directory, snapshot, last, resolution=None):
    directory.mkdir(parents=True, exist_ok=True)
    recover(directory)
    run_id = snapshot['run_id']
    version = f'snapshots/{run_id}.json'
    if (directory/version).exists(): raise ValueError('Snapshot already exists')
    history = directory/'history.csv'
    old = history.read_text(encoding='utf-8') if history.exists() else ''
    header = next(csv.reader(io.StringIO(old)), FIELDS) if old else FIELDS
    if not set(FIELDS).issubset(header): raise ValueError('Incompatible history header')
    buf = io.StringIO(newline=''); writer = csv.DictWriter(buf, fieldnames=header)
    if not old: writer.writeheader()
    for i, q in enumerate(snapshot['observations']):
        row = {k: snapshot.get(k) for k in ('run_id', 'monitor_id', 'stage', 'comparison_key')}
        row.update(schema_version=1, status='observed', evidence_ref=version+f'#/observations/{i}',
                   amount=q.get('total_amount'), currency=evidence(q, 'currency'),
                   hotel_key=q.get('hotel_data_id'), room_key=q.get('room_name'), rate_key=q.get('rate_key'))
        row.update({k: q.get(k) for k in ('observed_at', 'source', 'price_scope', 'tax_fee_inclusion', 'filter_status', 'room_match', 'comparison_status')})
        writer.writerow(row)
    encoded = json.dumps(snapshot, ensure_ascii=False, indent=2)
    files = {version: encoded, 'history.csv': old+buf.getvalue(), 'latest.json': encoded,
             'last-run.json': json.dumps(last, ensure_ascii=False, indent=2)}
    if resolution is not None:
        files['property-resolution.json'] = json.dumps(resolution, ensure_ascii=False, indent=2)
    atomic(directory/'.transaction.json', json.dumps({'files': files}, ensure_ascii=False))
    recover(directory)


def location(config, monitor_id, root):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', monitor_id): raise ValueError('Invalid monitor ID')
    path = (root/config['persistence_root']/monitor_id).resolve()
    if not path.is_relative_to(root.resolve()): raise ValueError('Persistence outside repository')
    return path


def normalized_name(value):
    return re.sub(r'[^\w]', '', value.casefold()) if isinstance(value, str) else ''


def invalid_property_token_error(error):
    """Retry discovery only for an explicit provider rejection of this token."""
    if not isinstance(error, SearchAPIError):
        return False
    d = error.diagnostics
    if (d.get('provider') != 'searchapi.io' or
            d.get('request_parameters', {}).get('engine') != 'google_hotels_property'):
        return False
    if d.get('category') == 'http_error':
        if d.get('http_status') not in (400, 404, 422):
            return False
    elif d.get('category') == 'api_error':
        if d.get('http_status') not in (None, 200):
            return False
    else:
        return False
    description = ' '.join(str(d.get(k) or '') for k in ('error_type', 'message'))
    return bool(re.search(r'property[_\s-]*token', description, re.I) and
                re.search(r'\b(?:invalid|expired|unknown|not[_\s-]*found|malformed)\b', description, re.I))


def trusted_resolution(directory, m):
    path = directory/'property-resolution.json'
    if m['stage'] != 'booked_room_compare' or not path.exists():
        return None
    resolution = json.loads(path.read_text(encoding='utf-8'))
    source_id = m['hotel_identity'].get('source_ids', {}).get('searchapi.io')
    names = [m['hotel_identity']['name']] + m['hotel_identity'].get('discovery_aliases', [])
    token = resolution.get('property_token')
    proof = resolution.get('evidence', {})
    try:
        observed = datetime.fromisoformat(proof['observed_at'])
        proof_valid = observed.tzinfo is not None and observed <= datetime.now(timezone.utc)
    except (KeyError, TypeError, ValueError):
        proof_valid = False
    version = resolution.get('schema_version')
    if (version not in (1, 2) or resolution.get('provider') != 'searchapi.io' or not source_id or
            resolution.get('data_id') != source_id or
            normalized_name(resolution.get('hotel_name')) not in {normalized_name(name) for name in names} or
            (token not in (None, '') and
             (not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', token))) or
            proof.get('source') not in ('searchapi.io/google_hotels', 'configured_property_token') or
            not proof.get('source_path') or not proof_valid or
            (version == 2 and (not resolution.get('monitor_id') or not resolution.get('configured_hotel_name'))) or
            (resolution.get('monitor_id') and resolution['monitor_id'] != m['monitor_id']) or
            (resolution.get('configured_hotel_name') and
             normalized_name(resolution['configured_hotel_name']) != normalized_name(m['hotel_identity']['name']))):
        raise ValueError('Stored hotel property resolution conflicts with configured identity')
    configured = m.get('search', {}).get('property_token')
    if configured and configured != token:
        raise ValueError('Configured and stored hotel property tokens conflict')
    return resolution if token else None


def collect(config, m, client, rejected_token=None):
    p = parameters(m, config['api']['query_currency'], config['api']['hl'], config['api']['gl'])
    query = m.get('search', {}).get('query') or (m['hotel_identity']['name'] if m['stage'] == 'booked_room_compare' else m['hard_filters']['location']['anchor']+' hotels')
    pinned = m.get('search', {}).get('property_token')
    if pinned:
        token_evidence = m.get('search', {}).get('property_token_evidence') or {}
        if (m['stage'] != 'booked_room_compare' or not token_evidence.get('source') or
                not token_evidence.get('reference') or not m['hotel_identity'].get('source_ids', {}).get('searchapi.io')):
            raise ValueError('Confirmed token evidence required for booked hotel')
        # kgmid and arbitrary name-derived IDs are not property tokens.
        if not isinstance(pinned, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', pinned):
            raise ValueError('Invalid property token')
        data = {'properties': [{'type': 'hotel', 'name': m['hotel_identity']['name'],
                               'data_id': m['hotel_identity'].get('source_ids', {}).get('searchapi.io'),
                               'property_token': pinned}]}
    else:
        data = client.search(dict(p, engine='google_hotels', q=query, property_type='hotel'))
    if not isinstance(data.get('properties'), list): raise ValueError('Missing hotel results')
    hotels = data['properties']
    if m['stage'] == 'booked_room_compare':
        source_id = m['hotel_identity'].get('source_ids', {}).get('searchapi.io')
        names = [m['hotel_identity']['name']] + m['hotel_identity'].get('discovery_aliases', [])
        hotels = [h for h in hotels if (h.get('data_id') == source_id if source_id else normalized_name(h.get('name')) in {normalized_name(n) for n in names})]
    completed, deferred, rows = [], [], []
    resolution = None
    if m['stage'] == 'booked_room_compare' and not hotels:
        deferred.append('target_hotel_not_identified')
    for h in hotels:
        if h.get('type') != 'hotel': continue
        if m['stage'] == 'booked_room_compare' and normalized_name(h.get('name')) not in {normalized_name(n) for n in names}:
            raise ValueError('Discovered hotel name conflicts with configured identity')
        key = h.get('data_id') or h.get('name')
        if not h.get('property_token'): raise ValueError('Hotel token missing')
        if h['property_token'] == rejected_token:
            raise ValueError('Discovery returned rejected property token')
        if client.attempts >= client.limit:
            deferred.append(key); continue
        detail = client.search(dict(engine_parameters(p, config['api'], 'google_hotels_property'), engine='google_hotels_property', property_token=h['property_token']))
        if not isinstance(detail.get('property'), dict) or not detail['property'].get('name'):
            raise ValueError('Malformed hotel detail')
        for group in ('featured_offers', 'all_offers'):
            if group in detail['property'] and not isinstance(detail['property'][group], list):
                raise ValueError('Malformed offer group')
        if h.get('data_id') and detail['property'].get('data_id') != h['data_id']:
            raise ValueError('Hotel identity changed')
        if detail['property'].get('property_token') and detail['property']['property_token'] != h['property_token']:
            raise ValueError('Hotel property token changed')
        if m['stage'] == 'booked_room_compare' and normalized_name(detail['property']['name']) not in {normalized_name(n) for n in names}:
            raise ValueError('Hotel name changed')
        stamp = now()
        if m['stage'] == 'booked_room_compare' and source_id:
            resolution = {'schema_version': 2, 'monitor_id': m['monitor_id'],
                          'provider': 'searchapi.io', 'configured_hotel_name': m['hotel_identity']['name'],
                          'data_id': source_id, 'hotel_name': detail['property']['name'],
                          'property_token': h['property_token'],
                          'evidence': {'source': 'searchapi.io/google_hotels' if not pinned else 'configured_property_token',
                                       'source_path': 'properties[matching data_id].property_token' if not pinned else m['search']['property_token_evidence']['reference'],
                                       'observed_at': stamp}}
        for q in room_quotes(detail, p['currency']):
            if any(q.get(k) is not None and not positive(q[k]) for k in ('total_amount', 'nightly_amount')):
                raise ValueError('Malformed room price')
            q.update(observed_at=stamp, stay=m['stay'], party=m['party'], rate_key=digest([q['source'], q['room_name'], q['evidence_path']]), evidence={})
            for field in ('hotel_data_id', 'room_name', 'total_amount', 'nightly_amount', 'reported_num_guests'):
                if q.get(field) is not None:
                    q['evidence'][field] = {'field': field, 'literal_value': q[field], 'source': 'searchapi.io', 'repo_path': q['evidence_path'], 'observed_at': stamp}
            if q.get('smoking') is not None:
                room_path = q['evidence_path'].split('.rates[', 1)[0] + '.name'
                q['evidence']['smoking'] = {
                    'field': 'smoking', 'literal_value': q['smoking'],
                    'source': 'searchapi.io', 'repo_path': room_path,
                    'observed_at': stamp, 'derived_from': 'room_name',
                    'source_text': q['room_name']}
            rows.append(q)
        completed.append(key)
    # Stage 2 covers only the locked hotel; unrelated discovery pages are irrelevant.
    if m['stage'] == 'candidate_search' and data.get('pagination', {}).get('next_page_token'):
        deferred.append('additional_results_page')
    return rows, {'requested': [h.get('data_id') or h.get('name') for h in hotels],
                  'completed': completed, 'deferred': deferred, 'failed': [],
                  'provider': 'searchapi.io',
                  'resolution_mode': 'direct_token' if pinned else 'discovery'}, resolution


def execute(config, monitor_id, root=ROOT, client=None, allow_query=False, *,
            effective_request=None, persistence_directory=None, request_hash=None):
    m = next(m for m in config['monitors'] if m['monitor_id'] == monitor_id)
    if m['stage'] not in ('candidate_search', 'booked_room_compare'): raise ValueError('Invalid stage')
    effective_request = copy.deepcopy(effective_request if effective_request is not None else m)
    request_hash = request_hash or config_hash(effective_request)
    directory = persistence_directory or location(config, monitor_id, root)
    if not config['execution']['query_enabled'] and not allow_query:
        return {'status': 'skipped', 'reason': 'query_disabled',
                'effective_request': effective_request, 'config_hash': request_hash}
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory/'.lock'
    with lock.open('x') as f: f.write(str(os.getpid()))
    try:
        recover(directory)
        prior = json.loads((directory/'latest.json').read_text(encoding='utf-8')) if (directory/'latest.json').exists() else {}
        last = {'run_id': uuid.uuid4().hex, 'monitor_id': monitor_id, 'stage': m['stage'], 'started_at': now(),
                'status': 'error', 'snapshot_run_id': prior.get('run_id'), 'effective_request': effective_request,
                'config_hash': request_hash,
                'coverage': {'requested': ['searchapi.io'], 'completed': [], 'deferred': [], 'failed': []}}
        try:
            client = client or Client(os.environ.get(config['api']['key_env']), config['api'].get('max_requests_per_run', 5))
            cached = trusted_resolution(directory, m)
            query_monitor = copy.deepcopy(m)
            if cached and not query_monitor.get('search', {}).get('property_token'):
                query_monitor.setdefault('search', {})['property_token'] = cached['property_token']
                query_monitor['search']['property_token_evidence'] = {
                    'source': 'searchapi.io', 'reference': 'property-resolution.json'}
            try:
                rows, coverage, resolution = collect(config, query_monitor, client)
            except SearchAPIError as exc:
                if (not cached or m.get('search', {}).get('property_token') or
                        not invalid_property_token_error(exc) or
                        client.limit - client.attempts < 2):
                    raise
                rows, coverage, resolution = collect(config, m, client,
                                                      rejected_token=cached['property_token'])
                coverage['resolution_mode'] = 'fallback_discovery'
            else:
                if cached:
                    resolution = {**cached, 'schema_version': 2, 'monitor_id': monitor_id,
                                  'configured_hotel_name': m['hotel_identity']['name'],
                                  'hotel_name': resolution['hotel_name']}
            last.update(coverage=coverage, attempted_requests=client.attempts, ended_at=now())
            if coverage['deferred']:
                last['status'] = 'partial'
                atomic(directory/'last-run.json', json.dumps(last, ensure_ascii=False, indent=2))
                return last
            fingerprint = digest({'monitor': m, 'api': config['api'], 'execution': config['execution']})
            snapshot = {'schema_version': 1, 'monitor_id': monitor_id, 'stage': m['stage'], 'run_id': last['run_id'],
                        'checked_at': last['ended_at'], 'config_fingerprint': fingerprint, 'comparison_key': digest(m),
                        'effective_request': effective_request, 'config_hash': request_hash,
                        'coverage': coverage, 'observations': [assess(m, q, config['execution'].get('max_quote_age_hours'), last['ended_at']) for q in rows]}
            if resolution is not None:
                snapshot['property_resolution'] = resolution
            last.update(status='success', snapshot_run_id=last['run_id'])
            persist(directory, snapshot, last, resolution)
        except Exception as exc:
            if (directory/'.transaction.json').exists():
                # Prepared complete transaction: roll forward before another query.
                raise RuntimeError('Persistence interrupted; recovery required') from None
            last.update(status='error', ended_at=now(), error='Hotel query or validation failed', attempted_requests=getattr(client, 'attempts', 0))
            if isinstance(exc, SearchAPIError): last['error_diagnostics'] = exc.diagnostics
            last['coverage']['failed'] = ['searchapi.io']
            atomic(directory/'last-run.json', json.dumps(last, ensure_ascii=False, indent=2))
        return last
    finally: lock.unlink()


def run_request(config, envelope, root=ROOT, client=None, allow_query=False, *,
                config_path=None, allow_monitor_update=False, confirm_config_hash=None):
    """Execute one versioned request; only an explicit confirmation can update config."""
    effective, policy, request_hash = resolve_request(config, envelope)
    source_id = envelope.get('monitor_id')
    if policy == 'monitor':
        if not allow_monitor_update or confirm_config_hash != request_hash or config_path is None:
            raise ValueError('monitor persistence needs explicit matching config hash confirmation')
        config_path = Path(config_path).resolve()
        if not config_path.is_relative_to(Path(root).resolve()):
            raise ValueError('Monitor config must be inside repository')
    execution_id = source_id or 'adhoc-' + uuid.uuid4().hex
    executed = copy.deepcopy(effective)
    executed['monitor_id'] = execution_id
    scoped_config = copy.deepcopy(config)
    scoped_config['monitors'] = [executed]

    if policy == 'none':
        with tempfile.TemporaryDirectory() as temporary:
            result = execute(scoped_config, execution_id, Path(temporary), client, allow_query,
                             effective_request=effective, request_hash=request_hash)
    else:
        isolated = not source_id or bool(envelope.get('input')) or policy == 'monitor'
        directory = None
        if isolated:
            directory = (Path(root)/config['persistence_root']/'_runs'/uuid.uuid4().hex).resolve()
            if not directory.is_relative_to(Path(root).resolve()):
                raise ValueError('Persistence outside repository')
        result = execute(scoped_config, execution_id, root, client, allow_query,
                         effective_request=effective, persistence_directory=directory,
                         request_hash=request_hash)
        if policy == 'monitor' and result.get('status') == 'success':
            current = json.loads(config_path.read_text(encoding='utf-8'))
            if current != config:
                raise ValueError('Monitor config changed during run; result saved but config not updated')
            current['monitors'] = [effective if m['monitor_id'] == source_id else m
                                   for m in current['monitors']]
            atomic(config_path, json.dumps(current, ensure_ascii=False, indent=2) + '\n')
    result['source_monitor_id'] = source_id
    result['persist_policy'] = policy
    result['effective_request'] = effective
    result['config_hash'] = request_hash
    return result


def report(config, monitor_id, root=ROOT):
    directory = location(config, monitor_id, root)
    result = {'monitor_id': monitor_id, 'latest': None, 'last_run': None}
    if (directory/'.transaction.json').exists():
        return dict(result, status='recovery_required', new_alerts=[])
    for filename, key in (('latest.json', 'latest'), ('last-run.json', 'last_run')):
        if (directory/filename).exists(): result[key] = json.loads((directory/filename).read_text(encoding='utf-8'))
    m = next(m for m in config['monitors'] if m['monitor_id'] == monitor_id)
    result['config_matches'] = bool(result['latest'] and result['latest'].get('config_fingerprint') == digest({'monitor': m, 'api': config['api'], 'execution': config['execution']}))
    result['status'] = '尚未執行住宿監控' if not result['latest'] else 'stored_snapshot'
    # A read-only report never reissues historical alerts.
    result['new_alerts'] = []
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['run', 'report', 'run-request', 'resolve-request'])
    parser.add_argument('--config', default='travel/nagoya/hotel-monitor.json')
    parser.add_argument('--monitor')
    parser.add_argument('--request-file', help='Versioned JSON request for run-request')
    parser.add_argument('--allow-query', action='store_true', help='Authorize this manual run only; does not change config or schedules')
    parser.add_argument('--allow-monitor-update', action='store_true', help='Allow an explicitly confirmed saved-config update')
    parser.add_argument('--confirm-config-hash', help='Full SHA256 of the effective request being approved')
    args = parser.parse_args()
    config_path = ROOT/args.config
    config = json.loads(config_path.read_text(encoding='utf-8'))
    if args.mode in ('run-request', 'resolve-request'):
        if args.monitor or not args.request_file: parser.error('request mode needs --request-file and no --monitor')
        envelope = json.loads(Path(args.request_file).read_text(encoding='utf-8'))
        if args.mode == 'resolve-request':
            effective, policy, request_hash = resolve_request(config, envelope)
            result = {'effective_request': effective, 'config_hash': request_hash,
                      'persist_policy': policy, 'source_monitor_id': envelope.get('monitor_id')}
        else:
            result = run_request(config, envelope, allow_query=args.allow_query,
                                 config_path=config_path, allow_monitor_update=args.allow_monitor_update,
                                 confirm_config_hash=args.confirm_config_hash)
    else:
        if not args.monitor: parser.error('run/report needs --monitor')
        result = execute(config, args.monitor, allow_query=args.allow_query) if args.mode == 'run' else report(config, args.monitor)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get('status') in ('error', 'partial') else 0


if __name__ == '__main__': raise SystemExit(main())

