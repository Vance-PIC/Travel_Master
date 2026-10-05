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
        encoded = base64.b64encode(content).decode() + "\n"
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


class CloudPackagingTests(unittest.TestCase):
    def test_container_is_minimal_nonroot_and_docs_cover_remote_setup(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        self.assertEqual(
            dockerfile,
            (root / "mcp" / "Dockerfile").read_text(encoding="utf-8"),
        )
        self.assertIn("FROM python:3.12-slim", dockerfile)
        self.assertIn("COPY mcp/requirements.txt", dockerfile)
        self.assertIn("COPY mcp/*.py", dockerfile)
        self.assertNotIn("COPY .", dockerfile)
        self.assertIn("USER app", dockerfile)
        self.assertIn("mcp/remote_server.py", dockerfile)
        docs = (root / "docs" / "flight-mcp.md").read_text(encoding="utf-8")
        for setting in ("FLIGHT_MCP_BEARER_TOKEN", "FLIGHT_MCP_ALLOWED_HOST", "GITHUB_TOKEN",
                        "GITHUB_REPO", "SERPAPI_KEY", "PORT", "FLIGHT_MCP_TOKEN"):
            self.assertIn(setting, docs)
        self.assertIn("--bearer-token-env-var", docs)


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

        self.assertEqual(asyncio.run(check()), {"flight_search", "flight_booking_links", "flight_monitor", "flight_report"})

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


@unittest.skipUnless(SDK_AVAILABLE, "Install mcp/requirements.txt for routing tests")
class RemoteRoutingTests(unittest.TestCase):
    def test_local_readonly_tools_do_not_use_github(self):
        import flight_server
        import github_store

        with patch.dict(os.environ, {"FLIGHT_MCP_REMOTE": ""}), \
                patch.object(github_store, "get_file") as remote_read:
            status = flight_server.flight_monitor("status")
            report = flight_server.flight_report("current")
        remote_read.assert_not_called()
        self.assertEqual(status["trip_id"], "nagoya")
        self.assertEqual(report["trip_id"], "nagoya")

    def test_remote_status_and_current_report_read_github_snapshot(self):
        import flight_server
        import github_store

        files = {
            "travel/nagoya/flight-monitor.json": b'{"family_target_twd":50000}',
            "travel/nagoya/flights/last-run.json": b'{"status":"ok"}',
            "travel/nagoya/flights/latest.json": json.dumps({
                "checked_at": "2026-10-05T00:00:00Z", "status": "ok",
                "itineraries": [{"itinerary_key": str(n), "displayed_price_twd": n}
                                for n in range(8, 0, -1)],
                "market_candidates": [{"flight_number": "CI150"}],
            }).encode(),
        }
        with patch.dict(os.environ, {"FLIGHT_MCP_REMOTE": "1"}), \
                patch.object(github_store, "get_file", side_effect=files.__getitem__) as read:
            status = flight_server.flight_monitor("status")
            report = flight_server.flight_report("current")
        self.assertEqual(status["config"]["family_target_twd"], 50000)
        self.assertEqual(status["latest_checked_at"], "2026-10-05T00:00:00Z")
        self.assertEqual([x["displayed_price_twd"] for x in report["top_itineraries"]], [1, 2, 3, 4, 5])
        self.assertEqual(report["market_candidates"], [{"flight_number": "CI150"}])
        self.assertEqual(read.call_count, 4)

    def test_remote_run_dispatches_once_without_local_execution(self):
        import flight_server
        import github_store

        with patch.dict(os.environ, {"FLIGHT_MCP_REMOTE": "1"}), \
                patch.object(github_store, "dispatch_monitor", return_value={"status": "queued", "workflow_url": "https://github.com/example"}) as dispatch, \
                patch.object(flight_server.subprocess, "run") as local_run:
            result = flight_server.flight_monitor("run", mode="full_query", purchase_itinerary="CI154+CI151")
        dispatch.assert_called_once_with("full_query", "CI154+CI151")
        local_run.assert_not_called()
        self.assertEqual(result["status"], "queued")
        self.assertNotIn("exit_code", result)

    def test_remote_history_and_malformed_current_snapshot(self):
        import flight_server
        import github_store

        with patch.dict(os.environ, {"FLIGHT_MCP_REMOTE": "1"}), \
                patch.object(github_store, "get_file", return_value=b"itinerary_key,displayed_price_twd\nA,1\nB,2\n"):
            self.assertEqual(flight_server.flight_report("history", limit=1)["history"],
                             [{"itinerary_key": "B", "displayed_price_twd": "2"}])
        with patch.dict(os.environ, {"FLIGHT_MCP_REMOTE": "1"}), \
                patch.object(github_store, "get_file", return_value=b"{bad"):
            with self.assertRaisesRegex(github_store.GitHubStoreError, "invalid"):
                flight_server.flight_report("current")

    def test_remote_missing_credentials_surface_clear_error(self):
        import flight_server
        import github_store

        with patch.dict(os.environ, {"FLIGHT_MCP_REMOTE": "1"}), \
                patch.object(github_store, "get_file", side_effect=github_store.GitHubStoreError("GitHub credential is missing")):
            with self.assertRaisesRegex(github_store.GitHubStoreError, "credential is missing"):
                flight_server.flight_report("current")

    def test_remote_current_rejects_malformed_itineraries_cleanly(self):
        import flight_server
        import github_store

        with patch.dict(os.environ, {"FLIGHT_MCP_REMOTE": "1"}), \
                patch.object(github_store, "get_file", return_value=b'{"itineraries":["bad"]}'):
            with self.assertRaisesRegex(github_store.GitHubStoreError, "invalid"):
                flight_server.flight_report("current")

    def test_search_network_error_does_not_expose_key(self):
        import flight_server

        secret = "secret-serpapi-token"
        with patch.dict(os.environ, {"SERPAPI_KEY": secret}), \
                patch.object(flight_server.urllib.request, "urlopen",
                             side_effect=urllib.error.URLError("request-url?api_key=" + secret)):
            with self.assertRaises(RuntimeError) as failure:
                flight_server._serpapi({"engine": "google_flights"})
        self.assertNotIn(secret, str(failure.exception))

    def test_flight_search_auto_engine_merges_hybrid_results(self):
        import flight_server
        import ignav_client

        mock_ignav_res = {
            "itineraries": [
                {
                    "price": {"amount": 500.0, "currency": "USD"},
                    "outbound": {"carrier": "Tigerair Taiwan", "segments": [{"marketing_carrier_code": "IT", "flight_number": "206", "departure_airport": "TPE", "arrival_airport": "NGO", "departure_time_local": "2026-12-11T08:45:00", "arrival_time_local": "2026-12-11T12:25:00"}]},
                    "inbound": {"carrier": "Tigerair Taiwan", "segments": [{"marketing_carrier_code": "IT", "flight_number": "209", "departure_airport": "NGO", "arrival_airport": "TPE", "departure_time_local": "2026-12-18T21:15:00", "arrival_time_local": "2026-12-18T23:50:00"}]},
                    "bags": {"carry_on": 1},
                    "requires_self_transfer": False,
                    "ignav_id": "test-ignav-id-123",
                }
            ]
        }
        mock_serpapi_res = {
            "best_flights": [
                {
                    "price": 59562,
                    "flights": [
                        {"airline": "中華航空", "flight_number": "CI 154", "departure_airport": {"id": "TPE"}, "arrival_airport": {"id": "NGO"}, "travel_class": "Economy"}
                    ]
                }
            ]
        }

        with patch.object(ignav_client.IgnavClient, "search_round_trip", return_value=mock_ignav_res) as mock_ignav, \
                patch.object(flight_server, "_serpapi", return_value=mock_serpapi_res) as mock_serp:
            res = flight_server.flight_search(
                origin="TPE",
                destination="NGO",
                outbound_date="2026-12-11",
                inbound_date="2026-12-18",
                engine="auto",
            )
            mock_ignav.assert_called_once()
            mock_serp.assert_called_once()
            self.assertEqual(res["engine"], "auto")
            self.assertIn("results", res)
            sources = [r["source"] for r in res["results"]]
            self.assertIn("ignav", sources)
            self.assertIn("serpapi", sources)
            # Verify Ignav structural flags survived
            ignav_item = [r for r in res["results"] if r["source"] == "ignav"][0]
            self.assertEqual(ignav_item["bags"], {"carry_on": 1})
            self.assertFalse(ignav_item["requires_self_transfer"])
            self.assertEqual(ignav_item["ignav_id"], "test-ignav-id-123")

