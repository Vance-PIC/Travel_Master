"""Small GitHub API adapter for the remote Flight MCP server."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

API_ROOT = "https://api.github.com/repos"
DEFAULT_REPO = "Vance-PIC/Travel_Master"
WORKFLOW = "nagoya-flight-monitor.yml"
HOTEL_WORKFLOW = "hotel-monitor.yml"


class GitHubStoreError(RuntimeError):
    """A sanitized GitHub storage/dispatch error."""


def _repository() -> tuple[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPO", DEFAULT_REPO)
    if not token:
        raise GitHubStoreError("GitHub credential is missing")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or ".." in repo:
        raise GitHubStoreError("GitHub repository setting is invalid")
    return repo, token


def _request(method: str, path: str, payload: dict | None = None) -> tuple[int, bytes]:
    repo, token = _repository()
    url = f"{API_ROOT}/{repo}/{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Accept": "application/vnd.github+json",
                                              "Authorization": f"Bearer {token}",
                                              "X-GitHub-Api-Version": "2022-11-28",
                                              "User-Agent": "Travel_Master MCP"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        raise GitHubStoreError(f"GitHub {method} failed (HTTP {exc.code})") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise GitHubStoreError(f"GitHub {method} failed ({type(exc).__name__})") from None


def get_file(path: str) -> bytes:
    if not path or any(part in ("", ".", "..") for part in path.split("/")):
        raise GitHubStoreError("GitHub file path is invalid")
    escaped = urllib.parse.quote(path, safe="/")
    status, body = _request("GET", f"contents/{escaped}?ref=master")
    if status != 200:
        raise GitHubStoreError(f"GitHub file read failed (HTTP {status})")
    try:
        result = json.loads(body)
        if result["encoding"] != "base64":
            raise ValueError("Unexpected encoding")
        # GitHub Contents API line-wraps the base64 content field.
        encoded = "".join(result["content"].split())
        return base64.b64decode(encoded, validate=True)
    except (ValueError, KeyError, TypeError, binascii.Error):
        raise GitHubStoreError("GitHub file content is invalid") from None


def dispatch_flight_monitor(mode: str, purchase_itinerary: str | None) -> dict[str, str]:
    if mode not in ("monitor_query", "full_query"):
        raise GitHubStoreError("Monitoring mode is invalid")
    if purchase_itinerary is not None and not re.fullmatch(r"[A-Z0-9]+\+[A-Z0-9]+", purchase_itinerary):
        raise GitHubStoreError("Purchase itinerary key is invalid")
    status, _ = _request("POST", f"actions/workflows/{WORKFLOW}/dispatches",
                         {"ref": "master", "inputs": {"mode": mode,
                                                      "purchase_itinerary": purchase_itinerary or ""}})
    if status != 204:
        raise GitHubStoreError(f"GitHub workflow dispatch failed (HTTP {status})")
    repo = os.environ.get("GITHUB_REPO", DEFAULT_REPO)
    return {"status": "queued", "workflow_url": f"https://github.com/{repo}/actions/workflows/{WORKFLOW}"}


dispatch_monitor = dispatch_flight_monitor


def dispatch_hotel_monitor(monitor: str, request_json: str | None = None) -> dict[str, str]:
    if not monitor or not re.fullmatch(r"[A-Za-z0-9_-]+", monitor):
        raise GitHubStoreError("Hotel monitor ID is invalid")
    if request_json:
        try:
            parsed = json.loads(request_json)
            if not isinstance(parsed, dict):
                raise ValueError
        except Exception:
            raise GitHubStoreError("Hotel request JSON is invalid") from None
    status, _ = _request("POST", f"actions/workflows/{HOTEL_WORKFLOW}/dispatches",
                         {"ref": "master", "inputs": {"monitor": monitor,
                                                      "request_json": request_json or ""}})
    if status != 204:
        raise GitHubStoreError(f"GitHub workflow dispatch failed (HTTP {status})")
    repo = os.environ.get("GITHUB_REPO", DEFAULT_REPO)
    return {"status": "queued", "workflow_url": f"https://github.com/{repo}/actions/workflows/{HOTEL_WORKFLOW}"}

