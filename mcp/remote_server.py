"""Authenticated Streamable HTTP entry point for Cloud Run."""

from __future__ import annotations

import hmac
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings

import flight_server
import travel_server

ASGIApp = Callable[[dict[str, Any], Callable[..., Awaitable[Any]],
                    Callable[..., Awaitable[None]]], Awaitable[None]]


def make_authorized_app(inner: ASGIApp, token: str) -> ASGIApp:
    expected = ("Bearer " + token).encode("utf-8")

    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            await inner(scope, receive, send)
            return
        headers = scope.get("headers", [])
        supplied = next((value for name, value in headers if name.lower() == b"authorization"), b"")
        if scope["type"] != "http" or scope.get("path") != "/mcp" or not hmac.compare_digest(supplied, expected):
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b"Unauthorized"})
            return
        await inner(scope, receive, send)

    return app


def config_from_env() -> tuple[str, str, int]:
    token = os.environ.get("TRAVEL_MCP_BEARER_TOKEN") or os.environ.get("FLIGHT_MCP_BEARER_TOKEN", "")
    host = os.environ.get("TRAVEL_MCP_ALLOWED_HOST") or os.environ.get("FLIGHT_MCP_ALLOWED_HOST", "")
    if not token:
        raise ValueError("TRAVEL_MCP_BEARER_TOKEN or FLIGHT_MCP_BEARER_TOKEN is required for remote mode")
    if not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", host) or ".." in host:
        raise ValueError("FLIGHT_MCP_ALLOWED_HOST or TRAVEL_MCP_ALLOWED_HOST must be an exact hostname")
    try:
        port = int(os.environ.get("PORT", "8080"))
    except ValueError:
        raise ValueError("PORT must be an integer") from None
    if not 1 <= port <= 65535:
        raise ValueError("PORT is out of range")
    return token, host, port


def create_app(token: str, allowed_host: str, target_mcp: Any = None) -> ASGIApp:
    server_mcp = target_mcp if target_mcp is not None else flight_server.mcp
    server_mcp.settings.stateless_http = True
    server_mcp.settings.json_response = True
    server_mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[allowed_host],
        allowed_origins=["https://" + allowed_host],
    )
    return make_authorized_app(server_mcp.streamable_http_app(), token)


def main() -> None:
    token, host, port = config_from_env()
    os.environ["TRAVEL_MCP_REMOTE"] = "1"
    os.environ["FLIGHT_MCP_REMOTE"] = "1"
    os.environ["HOTEL_MCP_REMOTE"] = "1"
    import uvicorn

    uvicorn.run(create_app(token, host, target_mcp=travel_server.mcp), host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
