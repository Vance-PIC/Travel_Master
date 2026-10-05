import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from hotel_executor import run_request, execute
from hotel_request import resolve_request
from test_hotel_executor import monitor


def config():
    return {'persistence_root': 'hotels', 'execution': {'query_enabled': True},
            'api': {'query_currency': 'JPY', 'hl': 'en', 'gl': 'TW'},
            'monitors': [monitor()]}


class UnifiedRequestTests(unittest.TestCase):
    def test_saved_input_deep_merges_without_mutating_config(self):
        cfg = config(); original = copy.deepcopy(cfg)
        envelope = {'schema_version': 1, 'monitor_id': 'test',
                    'input': {'stay': {'check_in': '2027-07-12'}, 'party': {'adults': 3}}}
        effective, policy, hash_value = resolve_request(cfg, envelope)
        self.assertEqual(effective['stay']['check_out'], '2027-07-17')
        self.assertEqual(effective['party']['child_ages'], [9, 7])
        self.assertEqual(effective['party']['adults'], 3)
        self.assertEqual(policy, 'run')
        self.assertEqual(len(hash_value), 64)
        self.assertEqual(cfg, original)
        self.assertEqual(resolve_request(cfg, envelope)[2], hash_value)

    def test_adhoc_requires_complete_request_and_defaults_to_none(self):
        cfg = config()
        with self.assertRaises(ValueError):
            resolve_request(cfg, {'schema_version': 1, 'input': {'stage': 'candidate_search'}})
        request = copy.deepcopy(monitor()); request.pop('monitor_id')
        effective, policy, _ = resolve_request(cfg, {'schema_version': 1, 'input': request})
        self.assertEqual(effective, request)
        self.assertEqual(policy, 'none')

    def test_rejects_unknown_monitor_and_protected_override(self):
        cfg = config()
        with self.assertRaises(ValueError):
            resolve_request(cfg, {'schema_version': 1, 'monitor_id': 'missing'})
        with self.assertRaises(ValueError):
            resolve_request(cfg, {'schema_version': 1, 'monitor_id': 'test',
                                  'input': {'stage': 'booked_room_compare'}})

    def test_none_returns_metadata_without_writing_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(); client = Mock(attempts=1, limit=5)
            client.search.return_value = {'properties': []}
            result = run_request(cfg, {'schema_version': 1, 'monitor_id': 'test',
                                       'persist_policy': 'none'}, Path(tmp), client)
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['effective_request']['monitor_id'], 'test')
            self.assertEqual(len(result['config_hash']), 64)
            self.assertFalse((Path(tmp)/'hotels').exists())

    def test_override_run_is_isolated_and_metadata_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(); client = Mock(attempts=1, limit=5)
            client.search.return_value = {'properties': []}
            result = run_request(cfg, {'schema_version': 1, 'monitor_id': 'test',
                                       'input': {'stay': {'check_in': '2027-07-12'}},
                                       'persist_policy': 'run'}, Path(tmp), client)
            self.assertEqual(result['status'], 'success')
            self.assertFalse((Path(tmp)/'hotels/test').exists())
            runs = list((Path(tmp)/'hotels/_runs').iterdir())
            self.assertEqual(len(runs), 1)
            snapshot = json.loads((runs[0]/'latest.json').read_text())
            last = json.loads((runs[0]/'last-run.json').read_text())
            self.assertEqual(snapshot['effective_request']['stay']['check_in'], '2027-07-12')
            self.assertEqual(snapshot['config_hash'], last['config_hash'])
            self.assertEqual(snapshot['config_hash'], result['config_hash'])

    def test_monitor_policy_requires_explicit_hash_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(); path = Path(tmp)/'config.json'
            path.write_text(json.dumps(cfg))
            request = {'schema_version': 1, 'monitor_id': 'test',
                       'input': {'stay': {'check_in': '2027-07-12'}},
                       'persist_policy': 'monitor'}
            client = Mock(attempts=0, limit=5)
            with self.assertRaises(ValueError):
                run_request(cfg, request, Path(tmp), client, config_path=path)
            self.assertEqual(json.loads(path.read_text()), cfg)
            client.search.assert_not_called()

    def test_confirmed_monitor_policy_updates_only_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(); path = Path(tmp)/'config.json'
            path.write_text(json.dumps(cfg))
            request = {'schema_version': 1, 'monitor_id': 'test',
                       'input': {'stay': {'check_in': '2027-07-12'}},
                       'persist_policy': 'monitor'}
            expected_hash = resolve_request(cfg, request)[2]
            client = Mock(attempts=1, limit=5)
            client.search.return_value = {'properties': []}
            result = run_request(cfg, request, Path(tmp), client, config_path=path,
                                 allow_monitor_update=True, confirm_config_hash=expected_hash)
            self.assertEqual(result['status'], 'success')
            self.assertEqual(json.loads(path.read_text())['monitors'][0]['stay']['check_in'], '2027-07-12')
            self.assertEqual(cfg['monitors'][0]['stay']['check_in'], '2027-07-11')

    def test_failed_monitor_run_does_not_update_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(); path = Path(tmp)/'config.json'
            path.write_text(json.dumps(cfg))
            request = {'schema_version': 1, 'monitor_id': 'test',
                       'input': {'stay': {'check_in': '2027-07-12'}},
                       'persist_policy': 'monitor'}
            client = Mock(attempts=0, limit=5)
            client.search.side_effect = RuntimeError('provider failed')
            result = run_request(cfg, request, Path(tmp), client, config_path=path,
                                 allow_monitor_update=True,
                                 confirm_config_hash=resolve_request(cfg, request)[2])
            self.assertEqual(result['status'], 'error')
            self.assertEqual(json.loads(path.read_text()), cfg)

    def test_legacy_saved_run_also_records_effective_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(); client = Mock(attempts=1, limit=5)
            client.search.return_value = {'properties': []}
            self.assertEqual(execute(cfg, 'test', Path(tmp), client)['status'], 'success')
            snapshot = json.loads((Path(tmp)/'hotels/test/latest.json').read_text())
            last = json.loads((Path(tmp)/'hotels/test/last-run.json').read_text())
            self.assertEqual(snapshot['effective_request'], cfg['monitors'][0])
            self.assertEqual(snapshot['config_hash'], last['config_hash'])


if __name__ == '__main__': unittest.main()
