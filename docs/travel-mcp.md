# Travel_Master Unified MCP Server (Flight & Hotel)

This is the unified Model Context Protocol (MCP) server for Travel_Master, exposing seven core tools for LLM integration across flight and accommodation monitoring:

## Exposed Tools

| Category | Tool | Description | Quota Consumption |
| --- | --- | --- | --- |
| **Flight** | `flight_search` | Ad-hoc round-trip flight search supporting **SerpApi** (Google Flights) and **Ignav** dual engines (`engine="serpapi" \| "ignav" \| "both"`). | Consumes SerpApi / Ignav quota based on engine |
| **Flight** | `flight_booking_links` | Retrieve direct booking URLs (airline official & OTAs like Trip.com) via Ignav. | Consumes Ignav quota |
| **Flight** | `flight_monitor` | Managed monitor execution (`run`) or inspection (`status`) for Nagoya flight route. | `run` consumes SerpApi quota; `status` is read-only |
| **Flight** | `flight_report` | Read current snapshot or history of flight itineraries. | Purely read-only; no API quota consumed |
| **Hotel** | `hotel_search` | Ad-hoc Google Hotels search via SearchAPI. | Consumes SearchAPI quota |
| **Hotel** | `hotel_monitor` | Managed hotel monitor execution (`run`) or inspection (`status`) for `marunouchi-booked` or `airport-candidate`. | `run` consumes SearchAPI quota; `status` is read-only |
| **Hotel** | `hotel_report` | Read current snapshot or history of hotel quotes and assessments. | Purely read-only; no API quota consumed |

---

## API Key Resolution Strategy (Three-Tier Fallback)

For `Ignav_KEY` (as well as `SERPAPI_KEY` and `SEARCHAPI_KEY`), the server resolves keys using a strict three-tier fallback order:
1. **Local `.env` file** (highest priority; automatically ignored in git)
2. **Process Environment Variables** (`os.environ`)
3. **Windows User/System Registry** (`HKCU\Environment` & `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment`)

---

## Local Development (stdio transport)

From the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r mcp/requirements.txt

# Option 1: Configure in .env (Recommended)
# Ignav_KEY=your_key
# SERPAPI_KEY=your_key
# SEARCHAPI_KEY=your_key

# Option 2: Set environment variables
$env:Ignav_KEY="..."
$env:SERPAPI_KEY="..."
$env:SEARCHAPI_KEY="..."

# Run unified MCP server locally
python mcp/travel_server.py
```

### Local MCP Client Configuration (e.g. Claude Desktop / Cursor / Antigravity)

```json
{
  "mcpServers": {
    "travel-master": {
      "command": "python",
      "args": ["C:/Users/P10377167/OneDrive - 統一資訊股份有限公司/Home/Travel_Master/mcp/travel_server.py"],
      "env": {
        "Ignav_KEY": "YOUR_IGNAV_KEY",
        "SERPAPI_KEY": "YOUR_SERPAPI_KEY",
        "SEARCHAPI_KEY": "YOUR_SEARCHAPI_KEY"
      }
    }
  }
}
```

---

## Cloud Run Remote Deployment (Streamable HTTP)

The remote server exposes the unified MCP tools over Streamable HTTP at `https://HOST/mcp`. It validates a bearer token on every request before processing any MCP protocol operations.

### Required Environment Settings & Secrets

| Environment Variable / Secret | Type | Purpose |
| --- | --- | --- |
| `TRAVEL_MCP_BEARER_TOKEN` | Secret | High-entropy shared bearer token for MCP clients (also accepts `FLIGHT_MCP_BEARER_TOKEN` for backward compatibility). |
| `TRAVEL_MCP_ALLOWED_HOST` | Env | Exact Cloud Run hostname without `https://` or `/mcp` (e.g. `travel-mcp-xyz.a.run.app`). |
| `GITHUB_TOKEN` | Secret | Fine-grained GitHub token for `Vance-PIC/Travel_Master` with `Contents: read` and `Actions: write`. |
| `GITHUB_REPO` | Env | Repository slug (`Vance-PIC/Travel_Master`). |
| `Ignav_KEY` | Secret | Used for Ignav flight search and booking link generation. |
| `SERPAPI_KEY` | Secret | Used for ad-hoc `flight_search` via Google Flights. |
| `SEARCHAPI_KEY` | Secret | Used for ad-hoc `hotel_search` via Google Hotels. |
| `PORT` | Env | Automatically injected by Cloud Run (defaults to 8080). |

---

## Architectural Principles

1. **Dual Engine Synergy**: Combines Google Flights' comprehensive route scheduling with Ignav's direct OTA/airline booking links.
2. **Adapter Boundary**: MCP tools are strictly adapters. All core evaluation rules and monitoring policies reside in `skills/flight-monitor`, `skills/hotel-monitor`, `scripts/nagoya_flight_monitor.py`, and `scripts/hotel_executor.py`.
3. **Quota Protection**: Read-only tools (`*_report` and `*_monitor(action='status')`) never consume third-party API quotas.
4. **No Raw Price Inference**: LLMs are advised not to multiply or extrapolate single-room or single-person prices into family totals without explicit Stage assessment.
