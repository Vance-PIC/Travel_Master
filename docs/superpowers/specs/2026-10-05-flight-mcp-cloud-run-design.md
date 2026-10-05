# Flight MCP Cloud Run design

Date: 2026-10-05
Status: Design for user review

## Goal and scope

Make the existing three-tool Flight MCP reachable from Codex on another computer while the user's Windows computer is off. Prefer Google Cloud Run's request-based free allowance, with billing enabled and no promise of a zero bill. Preserve the flight-monitor policy and GitHub repository as the source of truth for Nagoya monitoring data. Do not run paid SerpApi searches during implementation tests.

The existing STDIO entry point continues to work locally. This change adds a remote HTTPS entry point and cloud adapters; it does not create new flight-search or monitoring rules. It does not enable, disable, or change any workflow schedule.

## Options considered

- **Cloud Run, stateless adapter (selected):** scales to zero, has a managed HTTPS URL, and reads/dispatches via GitHub APIs. Requires a Google Cloud billing project and deployment secrets. Cold starts are possible.
- **Render web service:** simpler dashboard setup, but the free instance sleeps after inactivity and can take about a minute to wake; the always-on entry plan has a monthly charge. Its filesystem is ephemeral unless additional storage is arranged.
- **Persistent VM:** can run the current checkout directly, but needs continuous billing, operating-system maintenance, HTTPS, and safe Git synchronization. It is unnecessary for this small MCP adapter.

## Components and data flow

1. Extend `mcp/flight_server.py` with an explicit HTTP launch mode while preserving STDIO as the default. Expose the SDK's Streamable HTTP endpoint at `/mcp`. Bind to the Cloud Run-provided `PORT`, and run a stateless HTTP session so no user data depends on one container instance. The exact hosting command may be placed in a small launcher module if that keeps the original tool definitions unchanged.
2. Require an `Authorization: Bearer ...` value on every `/mcp` request, including initialization and tool calls. Compare the supplied value against `FLIGHT_MCP_BEARER_TOKEN` in constant time; refuse startup if the secret is absent in remote mode. Codex clients store the matching token in their own environment and reference it with `bearer_token_env_var`, not a literal in `config.toml`. Cloud Run provides HTTPS. Configure allowed hosts/origins for the deployed hostname; do not expose an unauthenticated server.
3. Keep `flight_search`'s existing query construction and raw-price response. It calls SerpApi from Cloud Run with the server-side `SERPAPI_KEY`. It does not persist results or infer a family price. The remote layer does not add flight-search retries or background polling.
4. In remote mode, `flight_report(current/history)` fetches the existing `latest.json` and `itinerary_history.csv` from the private GitHub repository using a narrowly scoped `GITHUB_TOKEN`, then applies the same response shaping as the local adapter. Missing/invalid files return a clear error or empty-history status, not a fabricated fresh snapshot. Read the default branch's committed files; no container-local copies are authoritative.
5. In remote mode, `flight_monitor(status)` reads committed `latest.json`/`last-run.json` from GitHub. `flight_monitor(run)` dispatches the existing `nagoya-flight-monitor.yml` with its `mode` and optional `purchase_itinerary`. Return an accepted/queued response with the workflow link; do not claim completion or invent a run ID from GitHub's dispatch acknowledgement. GitHub Actions remains responsible for running `scripts/nagoya_flight_monitor.py` and committing the results. The MCP server never runs a second monitor process or writes monitoring history itself.
6. Add a Cloud Run container/build description and deployment instructions. `mcp/requirements.txt` remains the dependency source. Cloud Run startup reads `PORT`. GitHub and SerpApi credentials, plus the MCP bearer token, are injected through cloud secret configuration; no secret value appears in source, Docker layers, deployment files, logs, or tool responses.

## Interface and behavior

Keep tool names and existing arguments: `flight_search`, `flight_monitor`, and `flight_report`. Local STDIO behavior remains unchanged. Remote `flight_monitor(run)` necessarily becomes asynchronous because GitHub Actions queues the run; the response explicitly says `queued` and instructs callers to use `flight_monitor(status)` or `flight_report` after the workflow finishes. `trip_id` remains limited to `nagoya` for managed monitoring. `flight_search` remains ad hoc for arbitrary routes.

GitHub credentials should be restricted to this repository with Contents: read and Actions: write. No API key should be passed to a tool argument. An unauthorized HTTP request must receive a rejection before any tool handler runs. Credential or GitHub failures must be sanitized; they must not leak request URLs containing tokens.

## Tests and acceptance

- Unit tests cover bearer rejection/acceptance, missing remote secrets, GitHub file read/parse and workflow dispatch responses with mocked HTTP; no live SerpApi, GitHub dispatch, or Cloud Run billing.
- An HTTP MCP client must initialize and list exactly the existing three tools. Existing STDIO initialization/listing must still pass.
- Mocked `flight_search` retains `stops=1` for nonstop and returns `price_scope=unknown`. Mocked `flight_monitor(run)` dispatches at most once with the user's arguments; report/status make only GitHub reads.
- Verify no local formal monitoring file changes and run existing repository tests. Build the container if tooling is available; otherwise report that check as unverified.
- After a Google Cloud project, billing, and secrets are available, deploy to Cloud Run and verify unauthenticated requests are rejected and authenticated Codex can list tools. A live SerpApi query or monitor run is a separate explicit test because it may consume quota or alter formal history.

## Deployment limits and user decisions

The user must supply or create a Google Cloud project with billing enabled and provision the three secret values on the cloud side. The existing GitHub Actions secret is not readable by Cloud Run; it must be provided separately. Cloud Run's free allowance is a usage threshold, not a guarantee of zero cost. The server is usable while the personal computer is off only after a real Cloud Run deployment and remote Codex registration. Until then, local STDIO remains the only live server.

Official references: [Codex MCP connection](https://learn.chatgpt.com/docs/extend/mcp?surface=app), [Cloud Run pricing](https://cloud.google.com/run/pricing), [GitHub workflow dispatch API](https://docs.github.com/en/rest/actions/workflows), [MCP Python SDK Streamable HTTP](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/index.md).
