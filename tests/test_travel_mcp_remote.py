import asyncio
import importlib.util
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

try:
    SDK_AVAILABLE = importlib.util.find_spec("mcp.server.fastmcp") is not None
except (ImportError, ModuleNotFoundError):
    SDK_AVAILABLE = False


class TravelPackagingTests(unittest.TestCase):
    def test_container_and_config(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("FROM python:3.12-slim", dockerfile)
        self.assertIn("COPY mcp/requirements.txt", dockerfile)
        self.assertIn("COPY mcp/*.py", dockerfile)
        self.assertIn("USER app", dockerfile)
        self.assertIn("mcp/remote_server.py", dockerfile)


@unittest.skipUnless(SDK_AVAILABLE, "Install mcp/requirements.txt for HTTP MCP tests")
class RemoteTravelConfigTests(unittest.TestCase):
    def test_remote_configuration_supports_travel_token_and_host(self):
        import remote_server

        # Test with TRAVEL_MCP variables
        with patch.dict(os.environ, {
            "TRAVEL_MCP_BEARER_TOKEN": "travel-secret-123",
            "TRAVEL_MCP_ALLOWED_HOST": "travel.example.com",
            "PORT": "9000",
        }, clear=True):
            token, host, port = remote_server.config_from_env()
            self.assertEqual(token, "travel-secret-123")
            self.assertEqual(host, "travel.example.com")
            self.assertEqual(port, 9000)

        # Test fallback to FLIGHT_MCP variables
        with patch.dict(os.environ, {
            "FLIGHT_MCP_BEARER_TOKEN": "flight-secret-456",
            "FLIGHT_MCP_ALLOWED_HOST": "flight.example.com",
            "PORT": "8080",
        }, clear=True):
            token, host, port = remote_server.config_from_env()
            self.assertEqual(token, "flight-secret-456")
            self.assertEqual(host, "flight.example.com")
            self.assertEqual(port, 8080)

        # Missing token
        with patch.dict(os.environ, {"TRAVEL_MCP_ALLOWED_HOST": "host.run.app"}, clear=True):
            with self.assertRaises(ValueError):
                remote_server.config_from_env()

        # Missing host
        with patch.dict(os.environ, {"TRAVEL_MCP_BEARER_TOKEN": "secret"}, clear=True):
            with self.assertRaises(ValueError):
                remote_server.config_from_env()


@unittest.skipUnless(SDK_AVAILABLE, "Install mcp/requirements.txt for HTTP MCP tests")
class TravelRemoteTransportTests(unittest.TestCase):
    def test_http_mcp_initializes_and_lists_all_six_tools(self):
        import httpx
        import remote_server
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async def check():
            app = remote_server.create_app("test-token", "cloud.test", target_mcp=remote_server.travel_server.mcp)
            transport = httpx.ASGITransport(app=app)
            async with remote_server.travel_server.mcp.session_manager.run():
                async with httpx.AsyncClient(transport=transport, base_url="https://cloud.test",
                                             headers={"Authorization": "Bearer test-token"}) as client:
                    async with streamable_http_client("https://cloud.test/mcp", http_client=client) as streams:
                        async with ClientSession(streams[0], streams[1]) as session:
                            await session.initialize()
                            listed = await session.list_tools()
                            return {tool.name for tool in listed.tools}

        expected = {
            "flight_search", "flight_booking_links", "flight_monitor", "flight_report",
            "hotel_search", "hotel_monitor", "hotel_report",
        }
        self.assertEqual(asyncio.run(check()), expected)

    def test_auth_gate_rejects_unauthorized_requests(self):
        import remote_server

        app = remote_server.make_authorized_app(lambda s, r, send: send({"type": "http.response.start", "status": 200, "headers": []}), "secret")

        async def invoke(header_val):
            headers = [] if header_val is None else [(b"authorization", header_val)]
            sent = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(event):
                sent.append(event)

            await app({"type": "http", "path": "/mcp", "headers": headers}, receive, send)
            return sent[0]["status"]

        self.assertEqual(asyncio.run(invoke(None)), 401)
        self.assertEqual(asyncio.run(invoke(b"Bearer wrong")), 401)
        self.assertEqual(asyncio.run(invoke(b"Bearer secret")), 200)


if __name__ == "__main__":
    unittest.main()
