import base64
import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class GitHubStoreTests(unittest.TestCase):
    def test_read_committed_file_and_dispatch_once(self):
        import github_store

        content = b'{"status":"ok"}'
        encoded = base64.b64encode(content).decode()
        requests = []

        def respond(req, timeout):
            requests.append(req)
            if req.get_method() == "GET":
                return Response(json.dumps({"encoding": "base64", "content": encoded}).encode())
            reply = Response(b"")
            reply.status = 204
            return reply

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token", "GITHUB_REPO": "Vance-PIC/Travel_Master"}), \
                patch.object(github_store.urllib.request, "urlopen", side_effect=respond):
            self.assertEqual(github_store.get_file("travel/nagoya/flights/latest.json"), content)
            result = github_store.dispatch_monitor("monitor_query", None)

        self.assertEqual(result["status"], "queued")
        self.assertEqual(len(requests), 2)
        self.assertTrue(requests[0].full_url.endswith("/contents/travel/nagoya/flights/latest.json?ref=master"))
        self.assertEqual(json.loads(requests[1].data),
                         {"ref": "master", "inputs": {"mode": "monitor_query", "purchase_itinerary": ""}})
        self.assertNotIn("test-token", str(result))

    def test_missing_token_or_invalid_repository_never_calls_github(self):
        import github_store

        with patch.dict(os.environ, {"GITHUB_TOKEN": "", "GITHUB_REPO": "Vance-PIC/Travel_Master"}), \
                patch.object(github_store.urllib.request, "urlopen") as http:
            with self.assertRaises(github_store.GitHubStoreError):
                github_store.get_file("travel/nagoya/flights/latest.json")
            http.assert_not_called()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token", "GITHUB_REPO": "evil/../repo"}), \
                patch.object(github_store.urllib.request, "urlopen") as http:
            with self.assertRaises(github_store.GitHubStoreError):
                github_store.dispatch_monitor("monitor_query", None)
            http.assert_not_called()

    def test_github_404_and_bad_content_fail_without_token_leak(self):
        import github_store

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token", "GITHUB_REPO": "Vance-PIC/Travel_Master"}):
            with patch.object(github_store.urllib.request, "urlopen",
                              side_effect=urllib.error.HTTPError("https://api.github.com/test", 404, "missing", {}, None)):
                with self.assertRaises(github_store.GitHubStoreError) as failure:
                    github_store.get_file("travel/nagoya/flights/latest.json")
                self.assertNotIn("test-token", str(failure.exception))
            with patch.object(github_store.urllib.request, "urlopen",
                              return_value=Response(b'{"encoding":"base64","content":"?"}')):
                with self.assertRaises(github_store.GitHubStoreError):
                    github_store.get_file("travel/nagoya/flights/latest.json")
