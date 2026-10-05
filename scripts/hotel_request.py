"""Versioned input contract for saved and ad-hoc hotel monitor runs."""
import copy
import hashlib
import json

from hotel_searchapi import parameters


def config_hash(effective_request):
    canonical = json.dumps(effective_request, sort_keys=True, ensure_ascii=False,
                           separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def merge(base, runtime):
    result = copy.deepcopy(base)
    for key, value in runtime.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def validate(effective, config):
    stage = effective.get('stage')
    if stage not in ('candidate_search', 'booked_room_compare'):
        raise ValueError('A supported hotel stage is required')
    stay, party = effective.get('stay'), effective.get('party')
    if not isinstance(stay, dict) or not isinstance(party, dict):
        raise ValueError('Complete stay and party are required')
    if 'rooms' not in party or type(party.get('adults')) is not int or party['adults'] < 1 or \
            type(party.get('children')) is not int or party['children'] < 0 or \
            type(party.get('rooms')) not in (int, type(None)) or \
            (type(party.get('rooms')) is int and party['rooms'] < 1):
        raise ValueError('Invalid party')
    try:
        parameters(effective, config['api']['query_currency'], config['api']['hl'], config['api']['gl'])
    except (KeyError, TypeError) as exc:
        raise ValueError('Incomplete stay or party') from exc
    if stage == 'candidate_search':
        hard = effective.get('hard_filters')
        if not isinstance(hard, dict) or not isinstance(hard.get('location'), dict) or \
                not isinstance(hard['location'].get('anchor'), str) or not hard['location']['anchor'].strip():
            raise ValueError('Candidate search needs a location anchor')
    else:
        for key in ('hotel_identity', 'room_baseline', 'booking_baseline', 'alert'):
            if not isinstance(effective.get(key), dict):
                raise ValueError(f'Booked-room comparison needs {key}')
        if not effective['hotel_identity'].get('name'):
            raise ValueError('Booked-room comparison needs hotel identity')


def resolve_request(config, envelope):
    if not isinstance(envelope, dict) or type(envelope.get('schema_version')) is not int or \
            envelope['schema_version'] != 1 or \
            set(envelope) - {'schema_version', 'monitor_id', 'input', 'persist_policy'}:
        raise ValueError('Unsupported hotel request schema')
    monitor_id = envelope.get('monitor_id')
    runtime = envelope.get('input', {})
    if not isinstance(runtime, dict):
        raise ValueError('input must be an object')
    if monitor_id is not None:
        if not isinstance(monitor_id, str) or not monitor_id:
            raise ValueError('Invalid monitor ID')
        matches = [m for m in config['monitors'] if m.get('monitor_id') == monitor_id]
        if len(matches) != 1:
            raise ValueError('Unknown or duplicate monitor ID')
        if set(runtime) - {'stay', 'party', 'hard_filters', 'preferences'}:
            raise ValueError('Runtime input changes a protected monitor field')
        effective = merge(matches[0], runtime)
    else:
        if not runtime or 'monitor_id' in runtime:
            raise ValueError('Ad-hoc input must be a complete request without monitor_id')
        allowed = {'stage', 'stay', 'party', 'hard_filters', 'preferences', 'hotel_identity',
                   'room_baseline', 'booking_baseline', 'alert', 'sources', 'evidence',
                   'needs_evidence', 'search'}
        if set(runtime) - allowed:
            raise ValueError('Ad-hoc input contains unsupported fields')
        effective = copy.deepcopy(runtime)
    policy = envelope.get('persist_policy', 'run' if monitor_id else 'none')
    if policy not in ('none', 'run', 'monitor'):
        raise ValueError('Invalid persist_policy')
    if policy == 'monitor' and (not monitor_id or not runtime):
        raise ValueError('monitor persistence requires a saved monitor and changes')
    validate(effective, config)
    return effective, policy, config_hash(effective)
