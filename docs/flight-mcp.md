# Flight MCP MVP

This is the first MCP adapter for Travel_Master. It intentionally exposes only three tools:

1. `flight_search` — ad-hoc round-trip search for arbitrary routes. It consumes SerpApi quota and does not persist data.
2. `flight_monitor` — `run` or `status` for the existing managed production monitor. MVP managed execution is limited to `trip_id=nagoya`.
3. `flight_report` — `current` or `history`; read-only and does not consume SerpApi quota.

## Design boundary

The MCP server is an adapter, not a second copy of flight-monitor policy. Production monitoring rules remain authoritative in:

- `skills/flight-monitor/SKILL.md`
- `skills/flight-monitor/references/search-policy.md`
- `skills/flight-monitor/references/report-format.md`
- `scripts/nagoya_flight_monitor.py`

Do not duplicate or fork those rules inside the MCP layer.

## Install and run

From the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r mcp/requirements.txt
$env:SERPAPI_KEY="..."
python mcp/flight_server.py
```

The command above uses local MCP stdio transport. It reads monitoring files from
this checkout and runs the monitor locally. `flight_search` uses `SERPAPI_KEY`
from this computer's environment.

## Cloud Run remote transport

The remote service exposes the same three tools at `https://HOST/mcp` over
Streamable HTTP. It requires a bearer token on every request. Cloud Run may be
configured for public invoker access because the application itself checks the
token before processing MCP requests. Keep the URL and token private. Cloud Run
can scale to zero (`min-instances=0`) and may fit within its free allowance at
low use, but a Google Cloud billing project is required and usage can incur
charges. Set a billing budget and alert in your Google Cloud project.

Create the following Secret Manager secrets and grant the Cloud Run service
account access to them. Never enter their values in source, image, build
arguments, GitHub files, or deployment command lines:

| Runtime setting | Purpose |
| --- | --- |
| `FLIGHT_MCP_BEARER_TOKEN` | Random, high-entropy shared bearer secret for MCP clients. |
| `GITHUB_TOKEN` | Fine-grained GitHub token for `Vance-PIC/Travel_Master`, with Contents: read and Actions: write. |
| `SERPAPI_KEY` | Enables the existing ad-hoc `flight_search` tool. |

Set `GITHUB_REPO=Vance-PIC/Travel_Master` and `FLIGHT_MCP_ALLOWED_HOST` as
ordinary runtime environment variables. The latter must be the exact Cloud Run
hostname without `https://` or `/mcp`; set it to the assigned service hostname
after the first deployment. `PORT` is injected by Cloud Run. The service fails
startup if its bearer token or allowed host is missing. Cloud Run's service
account needs Secret Manager access; it does not need GitHub credentials in
the image. Use a dedicated service account with minimal permissions.

Build from the repository root so the Dockerfile can copy only `mcp/*.py` and
`mcp/requirements.txt`:

```sh
docker build -f mcp/Dockerfile -t REGION-docker.pkg.dev/PROJECT/REPOSITORY/flight-mcp:VERSION .
docker push REGION-docker.pkg.dev/PROJECT/REPOSITORY/flight-mcp:VERSION
```

Deploy that image to Cloud Run with request-based billing, minimum instances
zero, the three Secret Manager mappings above, `GITHUB_REPO`, and an initial
valid `FLIGHT_MCP_ALLOWED_HOST` placeholder. Once Cloud Run assigns the service
URL, update `FLIGHT_MCP_ALLOWED_HOST` to its exact hostname, creating a new
revision. Configure public invoker access so an ordinary Codex MCP client can
reach the application bearer gate. Restrict access to trusted token holders and
rotate the bearer secret if it is exposed. Cloud Run and Secret Manager roles,
image registry permissions, and billing must be configured in the user's
Google Cloud project; deployment is not performed by this repository change.

For example, after creating an Artifact Registry Docker repository and the
three Secret Manager secrets, replace the uppercase placeholders and run:

```sh
gcloud run deploy flight-mcp \
  --project PROJECT --region REGION \
  --image REGION-docker.pkg.dev/PROJECT/REPOSITORY/flight-mcp:VERSION \
  --service-account SERVICE_ACCOUNT \
  --allow-unauthenticated --min-instances 0 \
  --set-env-vars GITHUB_REPO=Vance-PIC/Travel_Master,FLIGHT_MCP_ALLOWED_HOST=placeholder.invalid \
  --set-secrets FLIGHT_MCP_BEARER_TOKEN=flight-mcp-bearer:latest,GITHUB_TOKEN=flight-github-token:latest,SERPAPI_KEY=flight-serpapi-key:latest

# Replace HOST with the hostname printed in the new Cloud Run service URL.
gcloud run services update flight-mcp --project PROJECT --region REGION \
  --update-env-vars FLIGHT_MCP_ALLOWED_HOST=HOST
```

The first revision is only for discovering the assigned hostname; the bearer
gate still protects it. Do not connect a client until the hostname update is
ready. The Secret Manager versions named here are examples; use your own
secret names. If your organization disallows public invoker access, a separate
identity-aware ingress design is required for the Codex client.

On **each computer** that will connect, set the same bearer value in a local
environment variable, for example `FLIGHT_MCP_TOKEN`, then register:

```sh
codex mcp add travel-flight --url https://HOST/mcp --bearer-token-env-var FLIGHT_MCP_TOKEN
```

Do not put the token value in the Codex command. Test the remote endpoint first
without a bearer token and expect HTTP 401. With the token, initialize MCP and
list the tools: `flight_search`, `flight_monitor`, `flight_report`. Tool listing
does not use SerpApi or trigger GitHub Actions. A later `flight_search` does
consume SerpApi quota; `flight_monitor(action="run")` queues one existing
GitHub Actions run and returns `status=queued`, not a completed result or run
ID. `flight_monitor(action="status")` and `flight_report` read committed
Nagoya monitoring files through GitHub and do not consume SerpApi quota. The
GitHub Actions workflow remains the only formal monitoring executor.

## MVP scope

`flight_search` accepts arbitrary origin/destination/dates/passenger counts/cabin/nonstop/currency/market/locale and an optional airline allow-list. It returns raw API displayed prices with `price_scope=unknown`; callers must never multiply the displayed price by passenger count.

Managed monitor creation for arbitrary trips is deliberately not included in MVP. The existing executor still has Nagoya-specific persistence paths. Generalizing managed trip creation/execution is the next step after MCP connectivity is proven.

## Safety / quota behavior

- `flight_search`: consumes SerpApi quota.
- `flight_monitor(action="run")`: consumes quota according to flight-monitor Skill policy.
- `flight_monitor(action="status")`: read-only.
- `flight_report`: read-only.
- No tool receives or returns the SerpApi key.
