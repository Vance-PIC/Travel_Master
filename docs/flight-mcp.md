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

The server uses MCP stdio transport.

## MVP scope

`flight_search` accepts arbitrary origin/destination/dates/passenger counts/cabin/nonstop/currency/market/locale and an optional airline allow-list. It returns raw API displayed prices with `price_scope=unknown`; callers must never multiply the displayed price by passenger count.

Managed monitor creation for arbitrary trips is deliberately not included in MVP. The existing executor still has Nagoya-specific persistence paths. Generalizing managed trip creation/execution is the next step after MCP connectivity is proven.

## Safety / quota behavior

- `flight_search`: consumes SerpApi quota.
- `flight_monitor(action="run")`: consumes quota according to flight-monitor Skill policy.
- `flight_monitor(action="status")`: read-only.
- `flight_report`: read-only.
- No tool receives or returns the SerpApi key.
