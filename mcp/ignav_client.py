#!/usr/bin/env python3
"""Ignav Flight API Client for Travel_Master.

Provides multi-source API key resolution:
1. Local .env file (highest priority)
2. Process environment variables (Ignav_KEY, IGNAV_KEY, IGNAV_API_KEY)
3. Windows User/System Registry (fallback)

Documentation: https://ignav.com/flight-mcp-server & https://ignav.com/api
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
IGNAV_BASE_URL = "https://ignav.com/api"


def _read_env_file() -> dict[str, str]:
    """Parse key=value pairs from .env without external dependencies."""
    if not ENV_FILE.exists():
        return {}
    env_vars: dict[str, str] = {}
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            if val:
                env_vars[key] = val
    except Exception:
        pass
    return env_vars


def _read_windows_registry(key_name: str) -> str | None:
    """Read environment variable from Windows registry if on Windows."""
    if os.name != "nt":
        return None
    try:
        import winreg
        hives = [
            (winreg.HKEY_CURRENT_USER, r"Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        ]
        for hive, subkey in hives:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, key_name)
                    if val and isinstance(val, str) and val.strip():
                        return val.strip()
            except Exception:
                continue
    except Exception:
        pass
    return None


def get_ignav_key() -> str | None:
    """Resolve Ignav API Key following the strict priority order.

    Priority:
    1. .env file
    2. os.environ
    3. Windows Registry
    """
    key_names = ["Ignav_KEY", "IGNAV_KEY", "IGNAV_API_KEY", "ignav_key"]

    # 1. Check .env file
    env_file_vars = _read_env_file()
    for name in key_names:
        if env_file_vars.get(name):
            return env_file_vars[name]

    # 2. Check os.environ
    for name in key_names:
        val = os.environ.get(name)
        if val and val.strip():
            return val.strip()

    # 3. Check Windows registry
    for name in key_names:
        val = _read_windows_registry(name)
        if val:
            return val

    return None


class IgnavError(RuntimeError):
    """Base exception for Ignav API errors."""


class IgnavClient:
    """Client for interacting with the Ignav Flight API."""

    def __init__(self, api_key: str | None = None, base_url: str = IGNAV_BASE_URL) -> None:
        self.api_key = api_key or get_ignav_key()
        self.base_url = base_url.rstrip("/")

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        headers = {
            "User-Agent": "Travel_Master Ignav Flight MCP Client/1.0",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["X-Api-Key"] = self.api_key

        body: bytes | None = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                content = response.read().decode("utf-8")
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as err:
            err_msg = f"HTTP {err.code}: {err.reason}"
            try:
                err_body = err.read().decode("utf-8")
                err_data = json.loads(err_body)
                if isinstance(err_data, dict) and "message" in err_data:
                    err_msg = f"{err_msg} - {err_data['message']}"
                elif isinstance(err_data, dict) and "error" in err_data:
                    err_msg = f"{err_msg} - {err_data['error']}"
            except Exception:
                pass
            raise IgnavError(f"Ignav API request failed: {err_msg}") from None
        except urllib.error.URLError as err:
            raise IgnavError(f"Ignav API network error: {err.reason}") from None
        except Exception as err:
            raise IgnavError(f"Ignav API call error: {err}") from None

    def health(self) -> dict[str, Any]:
        """Check Ignav API service health."""
        return self._request("health", method="GET")

    def search_round_trip(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str,
        adults: int = 1,
        children: int = 0,
        currency: str = "TWD",
        cabin_class: str = "economy",
    ) -> dict[str, Any]:
        """Search round-trip flight fares."""
        if not self.api_key:
            raise IgnavError("Ignav API Key is not configured (check .env, env vars, or registry).")
        payload: dict[str, Any] = {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "departure_date": departure_date,
            "return_date": return_date,
            "adults": adults,
        }
        if children > 0:
            payload["children"] = children
        if cabin_class and cabin_class != "economy":
            payload["cabin_class"] = cabin_class
        return self._request("fares/round-trip", method="POST", data=payload)

    def search_one_way(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        adults: int = 1,
        children: int = 0,
        currency: str = "TWD",
        cabin_class: str = "economy",
    ) -> dict[str, Any]:
        """Search one-way flight fares."""
        if not self.api_key:
            raise IgnavError("Ignav API Key is not configured (check .env, env vars, or registry).")
        payload: dict[str, Any] = {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "departure_date": departure_date,
            "adults": adults,
        }
        if children > 0:
            payload["children"] = children
        if cabin_class and cabin_class != "economy":
            payload["cabin_class"] = cabin_class
        return self._request("fares/one-way", method="POST", data=payload)

    def get_booking_links(self, ignav_id: str) -> dict[str, Any]:
        """Get direct booking links and booking options for an ignav flight ID."""
        if not self.api_key:
            raise IgnavError("Ignav API Key is not configured (check .env, env vars, or registry).")
        return self._request("fares/booking-links", method="POST", data={"ignav_id": ignav_id})

    def search_airports(self, query: str) -> dict[str, Any]:
        """Lookup airport by city name or IATA code."""
        return self._request("airports", method="GET", params={"q": query})
