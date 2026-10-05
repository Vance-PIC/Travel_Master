# Flight MCP Cloud Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the three existing Flight MCP tools available over authenticated HTTPS while preserving local STDIO and GitHub as the authoritative Nagoya monitor store.

**Architecture:** A stateless Cloud Run Streamable HTTP service serves the existing tools. The cloud adapter reads committed monitoring files and dispatches runs through GitHub APIs; the existing GitHub Actions workflow executes the monitor. The local STDIO path retains direct filesystem and subprocess behavior.

**Tech Stack:** Python 3.12, `mcp>=1.0,<2.0`, Starlette/uvicorn from the MCP SDK, standard-library `urllib`, GitHub REST API, Docker, Google Cloud Run.

**Spec:** `docs/superpowers/specs/2026-10-05-flight-mcp-cloud-run-design.md`

## Global Constraints

- Preserve `flight_search`, `flight_monitor`, and `flight_report` names and arguments.
- Do not change flight-monitor policy, trip configuration, or schedule.
- No live SerpApi or workflow-dispatch requests during implementation tests.
- Remote HTTP rejects missing/invalid bearer credentials before calling any tool.
- Use GitHub's committed Nagoya files as remote report/status data; never rely on the container filesystem for formal history.
- Do not put SerpApi, GitHub, or MCP bearer token values in source, container image, logs, or tool results.
- `flight_monitor(run)` returns queued/accepted, not a fabricated completed result or run ID.
- Deployment requires a user-provided Google Cloud billing project and cloud secrets; source changes alone are not a deployment.

## Review Focus

1. Missing GitHub credential: remote report/monitor must fail clearly before a network request. Task 1 tests this.
2. GitHub 404 or malformed committed JSON/CSV: report must not invent a current snapshot. Task 1 tests this.
3. Missing/incorrect MCP bearer header: no initialization or paid tool is reached. Task 2 tests this.
4. Remote monitor dispatch replay or duplicate calls: one request produces exactly one dispatch; response remains queued. Task 3 tests this.
5. STDIO regression: the three tool names and local readonly calls remain usable after remote routing. Task 4 tests this.

## File map

| File | Responsibility |
| --- | --- |
| `mcp/github_store.py` | Authenticated GitHub file reads and workflow dispatch, with sanitized errors. |
| `mcp/remote_server.py` | HTTP bearer gate, SDK Streamable HTTP app, Cloud Run host/port configuration. |
| `mcp/flight_server.py` | Existing three tools; select local or GitHub monitor store using explicit remote mode. |
| `mcp/Dockerfile` | Reproducible Cloud Run service image without secret values or monitoring data. |
| `docs/flight-mcp.md` | Local/remote setup, cloud secrets, Codex connection and cost/verification instructions. |
| `tests/test_flight_mcp_remote.py` | GitHub adapter, transport authorization, tool routing and STDIO regressions using mocks. |

### Task 1: GitHub monitor store

**Files:** Create `mcp/github_store.py`; create `tests/test_flight_mcp_remote.py`.

**Interfaces:** Produce `get_file(path: str) -> bytes` and `dispatch_monitor(mode: str, purchase_itinerary: str | None) -> dict`. `get_file` uses `GITHUB_REPO` and `GITHUB_TOKEN` from environment and reads `ref=master`. `dispatch_monitor` uses the same credentials and returns `{"status":"queued","workflow_url":...}` only on HTTP 204. A `GitHubStoreError` contains no token or request URL.

- [ ] **Step 1: Write failing tests** for absent credentials, valid base64 GitHub file content, 404, invalid JSON in a caller, one POST with exact workflow inputs, and non-204 dispatch. Mock `urllib.request.urlopen` and assert calls, response objects, and safe error strings. Example dispatch input assertion:

  ```python
  self.assertEqual(json.loads(request.data), {
      "ref": "master", "inputs": {"mode": "monitor_query", "purchase_itinerary": ""}
  })
  ```

- [ ] **Step 2: Run** `python -m unittest tests.test_flight_mcp_remote -v`; expect failures because `mcp/github_store.py` does not exist.
- [ ] **Step 3: Implement** `get_file` with `GET https://api.github.com/repos/{repo}/contents/{quoted_path}?ref=master`, base64 decode and explicit API status checks. Implement `dispatch_monitor` with `POST https://api.github.com/repos/{repo}/actions/workflows/nagoya-flight-monitor.yml/dispatches`; use headers `Accept: application/vnd.github+json`, `Authorization: Bearer <token>`, and `X-GitHub-Api-Version` supported by the chosen API version. Restrict `GITHUB_REPO` to owner/repo path characters; default to `Vance-PIC/Travel_Master`. Catch HTTP/network errors and raise only a sanitized `GitHubStoreError` with status/stage.
- [ ] **Step 4: Run** the focused test command again; expect all Task 1 cases to pass.
- [ ] **Step 5: Commit** the adapter and focused tests with `feat: add GitHub store for remote Flight MCP`.

### Task 2: Authenticated remote transport

**Files:** Create `mcp/remote_server.py`; extend `tests/test_flight_mcp_remote.py`.

**Interfaces:** Produce `create_app(token: str, allowed_host: str) -> ASGIApp` wrapping `flight_server.mcp.streamable_http_app()`. The wrapper checks all HTTP requests using `hmac.compare_digest` against `Authorization: Bearer <token>` and returns 401 without forwarding when invalid. `main()` requires `FLIGHT_MCP_BEARER_TOKEN` and `FLIGHT_MCP_ALLOWED_HOST`, sets `FLIGHT_MCP_REMOTE=1`, sets `mcp.settings.stateless_http=True` and exact-host transport security, then binds `0.0.0.0:$PORT` with uvicorn. Local STDIO keeps its current entry point.

- [ ] **Step 1: Write failing tests** that send mock ASGI HTTP scopes with missing, malformed, wrong and correct authorization headers; count downstream calls. Add a startup test with the bearer variable absent. For an authorized request:

  ```python
  self.assertEqual(forwarded, 1)
  self.assertEqual(unauthorized_statuses, [401, 401, 401])
  ```

- [ ] **Step 2: Run** the focused unittest module; expect failures because the remote launcher does not exist.
- [ ] **Step 3: Implement** the ASGI wrapper without echoing bearer values. Configure `TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=[allowed_host], allowed_origins=["https://" + allowed_host])` before creating the HTTP app. Use a default local port only in tests; production requires Cloud Run's valid `PORT` and exact deployed host setting. Keep auth enforced on every `/mcp` request and reject all other paths unless explicitly needed for the platform health check.
- [ ] **Step 4: Run** tests, then use an MCP HTTP client against a loopback test server to initialize and list the same three tools with a valid token; verify 401 without one. Do not invoke `flight_search` or `flight_monitor(run)` in this transport check.
- [ ] **Step 5: Commit** the transport and tests with `feat: serve Flight MCP over authenticated HTTP`.

### Task 3: Route remote monitor/report operations through GitHub

**Files:** Modify `mcp/flight_server.py`; extend `tests/test_flight_mcp_remote.py`.

**Interfaces:** In remote mode, `flight_monitor(status)` and `flight_report(current/history)` call `github_store.get_file`; `flight_monitor(run)` calls `github_store.dispatch_monitor`. When `FLIGHT_MCP_REMOTE` is absent, functions retain local file/subprocess operations. `flight_search` is unchanged except for using the injected cloud SerpApi credential.

- [ ] **Step 1: Write failing tests** with `FLIGHT_MCP_REMOTE=1` and mocked GitHub store. Verify current/history response shapes, retained Top 5 selection, one dispatch with correct mode/purchase key, no subprocess call, no local file write, and sanitized GitHub failures. Test the missing-credential and invalid-file cases from Review Focus.
- [ ] **Step 2: Run** focused tests; expect remote path failures while local tests still pass.
- [ ] **Step 3: Implement** small helpers such as `_monitor_json(name: str) -> dict` and `_monitor_history(limit: int) -> list[dict]` to reuse current response formatting. Decode GitHub bytes as UTF-8; reject invalid current JSON and CSV rows with a controlled error. Keep `trip_id=nagoya` and local STDIO behavior. Return `queued` plus workflow URL for remote runs; do not call the local monitor subprocess.
- [ ] **Step 4: Run** focused tests and `python -m unittest discover -s tests -v`; inspect `git diff` for changes outside MCP/docs/tests and confirm no SerpApi call was made.
- [ ] **Step 5: Commit** with `feat: read and dispatch remote monitor through GitHub`.

### Task 4: Cloud Run packaging and handoff

**Files:** Create `mcp/Dockerfile`; modify `docs/flight-mcp.md`; extend `tests/test_flight_mcp_remote.py` if integration coverage is missing.

**Interfaces:** The container starts `python mcp/remote_server.py`; `PORT`, `FLIGHT_MCP_ALLOWED_HOST`, `FLIGHT_MCP_BEARER_TOKEN`, `GITHUB_TOKEN`, `GITHUB_REPO`, and `SERPAPI_KEY` are runtime configuration. Codex uses the deployed `https://.../mcp` URL and `bearer_token_env_var` referencing a local secret.

- [ ] **Step 1: Write the failing packaging check** that parses the Dockerfile and asserts it copies only MCP service code/dependencies (no `travel/nagoya/flights` data or `.env`), runs as a non-root user and starts the remote launcher. Ensure documentation includes all runtime env names and `codex mcp add ... --url ... --bearer-token-env-var ...`.
- [ ] **Step 2: Run** the packaging check; expect failure before Dockerfile/docs exist.
- [ ] **Step 3: Implement** a Python 3.12 slim image, install `mcp/requirements.txt`, copy the `mcp/` package, create/use a non-root user, and set the launcher command. Document Cloud Run request-based billing/free allowance, Secret Manager injection, exact hostname setup, minimum instances 0, GitHub token permissions (Contents read, Actions write), bearer rotation, and Codex registration on each computer. Include explicit instructions for testing unauthorized/authenticated tool listing after deployment without triggering SerpApi or a monitor run.
- [ ] **Step 4: Run** focused and full tests plus `git diff --check`; build the Dockerfile only if Docker is available. If Docker or Google Cloud credentials are absent, record those checks as unverified instead of claiming deployment.
- [ ] **Step 5: Commit** with `docs: package and document remote Flight MCP` and prepare a reviewable branch/PR. Do not deploy or activate cloud billing automatically.

## Final verification and deployment

Review the complete diff against the design spec; verify no key, token, request URL with credentials, monitoring data, or policy changes entered the commit. Confirm remote HTTP and local STDIO both list the three tools. A deployed HTTPS URL, Cloud Run project, billing status and cloud secret configuration require the user's account context. Only after those exist can the real endpoint be tested from Codex. A live flight search and `flight_monitor(run)` remain separate quota-impacting operations.
