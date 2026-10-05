import base64
import asyncio
import importlib.util
import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))
try:
    SDK_AVAILABLE = importlib.util.find_spec("mcp.server.fastmcp") is not None
except (ImportError, ModuleNotFoundError):
    SDK_AVAILABLE = False


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


@unittest.skipUnless(SDK_AVAILABLE, "Install mcp/requirements.txt for HTTP MCP tests")
class RemoteTransportTests(unittest.TestCase):
    def test_http_mcp_initializes_and_lists_existing_tools(self):
        import httpx
        import remote_server
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async def check():
            app = remote_server.create_app("test-token", "cloud.test")
            transport = httpx.ASGITransport(app=app)
            async with remote_server.flight_server.mcp.session_manager.run():
                async with httpx.AsyncClient(transport=transport, base_url="https://cloud.test",
                                             headers={"Authorization": "Bearer test-token"}) as client:
                    async with streamable_http_client("https://cloud.test/mcp", http_client=client) as streams:
                        async with ClientSession(streams[0], streams[1]) as session:
                            await session.initialize()
                            listed = await session.list_tools()
                            return {tool.name for tool in listed.tools}

        self.assertEqual(asyncio.run(check()), {"flight_search", "flight_monitor", "flight_report"})

    def test_auth_gate_rejects_invalid_headers_before_app(self):
        import remote_server

        forwarded = []

        async def inner(scope, receive, send):
            forwarded.append(scope)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app = remote_server.make_authorized_app(inner, "expected-token")

        async def invoke(value):
            sent = []
            headers = [] if value is None else [(b"authorization", value)]
            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}
            async def send(event):
                sent.append(event)
            await app({"type": "http", "path": "/mcp", "headers": headers}, receive, send)
            return sent[0]["status"]

        async def run_cases():
            return await asyncio.gather(invoke(None), invoke(b"bad"), invoke(b"Bearer wrong"),
                                        invoke(b"Bearer expected-token"))

        statuses = asyncio.run(run_cases())
        self.assertEqual(statuses, [401, 401, 401, 200])
        self.assertEqual(len(forwarded), 1)

    def test_remote_configuration_requires_secret_and_exact_host(self):
        import remote_server

        with patch.dict(os.environ, {"FLIGHT_MCP_BEARER_TOKEN": "", "FLIGHT_MCP_ALLOWED_HOST": "x.run.app"}):
            with self.assertRaises(ValueError):
                remote_server.config_from_env()
        with patch.dict(os.environ, {"FLIGHT_MCP_BEARER_TOKEN": "secret", "FLIGHT_MCP_ALLOWED_HOST": ""}):
            with self.assertRaises(ValueError):
                remote_server.config_from_env()
