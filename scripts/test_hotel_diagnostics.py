import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch
from hotel_searchapi import Client, SearchAPIError, safe_text
from hotel_executor import execute
from test_hotel_executor import monitor


class DiagnosticsTests(unittest.TestCase):
    def test_request_parameters_are_allowlisted_and_redacted(self):
        opener = Mock(side_effect=OSError('private-key'))
        with self.assertRaises(SearchAPIError) as caught:
            Client('private-key', opener=opener).search({'engine': 'google_hotels_property',
                'q': 'Hotel private-key', 'property_token': 'opaque-value', 'Authorization': 'private-key',
                'check_in_date': '2027-07-11', 'hl': 'en-US', 'gl': 'TW', 'currency': 'JPY'})
        d = caught.exception.diagnostics
        self.assertEqual(d['request_parameters']['hl'], 'en-US')
        self.assertEqual(d['request_parameters']['check_in_date'], '2027-07-11')
        self.assertNotIn('private-key', json.dumps(d))
        self.assertNotIn('opaque-value', json.dumps(d))
        self.assertNotIn('Authorization', json.dumps(d))

    def test_encoded_keys_urls_and_unknown_credential_labels(self):
        text = 'bad %70rivate-key https://host/?key=unknown "client_secret":"unregistered-value" token=other-value Bearer bearer-value'
        cleaned = safe_text(text, 'private-key')
        for secret in ('private-key', 'unknown', 'unregistered-value', 'other-value', 'bearer-value'):
            self.assertNotIn(secret, cleaned)
        self.assertLessEqual(len(safe_text('x'*1000, 'private-key')), 500)

    def test_http_error_preserves_safe_fields_only(self):
        body = json.dumps({'error': {'type': 'InvalidParameter', 'message': 'Bad dates; Authorization: Bearer private-key\napi_key=private-key'},
                           'headers': {'Authorization': 'private-key'}}).encode()
        opener = Mock(side_effect=urllib.error.HTTPError('https://host/?api_key=private-key', 400, 'bad', {}, io.BytesIO(body)))
        with self.assertRaises(SearchAPIError) as caught:
            Client('private-key', opener=opener).search({'engine': 'google_hotels'})
        d = caught.exception.diagnostics
        self.assertEqual(d['http_status'], 400)
        self.assertEqual(d['error_type'], 'InvalidParameter')
        self.assertIn('Bad dates', d['message'])
        self.assertNotIn('private-key', json.dumps(d))
        self.assertNotIn('Authorization', json.dumps(d))
        self.assertEqual(opener.call_count, 1)

    def test_success_http_api_error_and_other_env_secret(self):
        response = io.StringIO('{"error":"Invalid token other-secret-value"}')
        with patch.dict('os.environ', {'OTHER_TOKEN': 'other-secret-value'}):
            with self.assertRaises(SearchAPIError) as caught:
                Client('key', opener=Mock(return_value=response)).search({'engine': 'google_hotels'})
        self.assertNotIn('other-secret-value', json.dumps(caught.exception.diagnostics))
        self.assertEqual(caught.exception.diagnostics['category'], 'api_error')

    def test_html_and_transport_do_not_expose_raw_content(self):
        for error in (OSError('private-key'), urllib.error.HTTPError('secret-url', 503, 'private-key', {}, io.BytesIO(b'<html>private-key</html>'))):
            with self.assertRaises(SearchAPIError) as caught:
                Client('private-key', opener=Mock(side_effect=error)).search({'engine': 'google_hotels'})
            self.assertNotIn('private-key', json.dumps(caught.exception.diagnostics))

    def test_executor_saves_safe_diagnostics_and_protects_history(self):
        cfg = {'persistence_root': 'hotels', 'execution': {'query_enabled': True},
               'api': {'query_currency': 'JPY', 'hl': 'en-US', 'gl': 'TW'}, 'monitors': [monitor()]}
        body = io.BytesIO(b'{"error":{"type":"quota_exceeded","message":"No remaining credits"}}')
        client = Client('private-key', opener=Mock(side_effect=urllib.error.HTTPError('url', 429, 'reason', {}, body)))
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)/'hotels/test'; d.mkdir(parents=True)
            (d/'latest.json').write_text('{"run_id":"old"}')
            (d/'history.csv').write_text('old')
            result = execute(cfg, 'test', Path(tmp), client)
            self.assertEqual(result['error_diagnostics']['http_status'], 429)
            self.assertEqual(json.loads((d/'last-run.json').read_text())['error_diagnostics']['error_type'], 'quota_exceeded')
            self.assertEqual((d/'history.csv').read_text(), 'old')
            self.assertNotIn('private-key', json.dumps(result))


if __name__ == '__main__': unittest.main()
