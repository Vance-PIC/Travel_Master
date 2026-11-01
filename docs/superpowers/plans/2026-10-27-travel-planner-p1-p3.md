# P1–P3 Travel Planner Implementation Plan

> **For implementation:** Execute the slices in order. This implementation follows `specs/travel-planner/P1-P3-flight-planning-spec.md` and keeps provider-dependent results explicitly sourced.

**Goal:** Add a durable P1 draft → P2 candidate monitoring → P3 selected itinerary decision flow to the existing Flight Tracker app.

**Architecture:** Add a dedicated `/planner` page and `/api/planner/*` routes to the existing FastAPI application. Persist drafts, exact outbound/return candidate pairs, monitoring state, and observations in additive SQLite tables. Use the existing Ignav client through a provider adapter; do not fabricate results or alter existing tracker routes. Keep credentials on the server. Children aged 12–17 are counted as adults for provider queries; ages under 2 are blocked from booking-total quotes because the current traveler model lacks lap/seat choice.

**Tech:** FastAPI, Pydantic, SQLite, existing `mcp.ignav_client`, standalone HTML/CSS/JS.

## Slices

1. **Persistence and provider boundary**
   - Add planner tables via additive `CREATE TABLE IF NOT EXISTS` schema initialization.
   - Add validation/normalization for airports, date ranges, travelers, exact flight-pair keys, prices and provider response variants.
   - Reuse Ignav key resolution and never expose keys or raw provider payloads to the browser.
2. **P1: draft and search**
   - Add draft create/read/update endpoints with airport keyword search and flexible outbound/return date ranges.
   - Search direct return-flight combinations for destinations/date combinations and return sourced fare observations.
   - Adding a candidate immediately starts tracking it; identity includes both dates and both flight numbers.
3. **P2: candidate tabs and price tracking**
   - Add candidate list, select/tab view, target price, pause/remove, manual refresh, and an automatic interval (24 hours by default, controlled by `PLANNER_REFRESH_INTERVAL_HOURS`).
   - Persist a new observation only when a provider returns a valid fare; calculate per-person trend from sourced observations.
4. **P3: decision and booking channels**
   - Select exactly one tracked candidate to confirm the itinerary.
   - Query booking-link options for that exact itinerary and passenger composition; present source, currency, price scope, availability and deep link.
   - Do not sort mixed currencies or call an unverified amount a party total. Show explicit unsupported/incomplete states.
5. **GUI wiring and handoff**
   - Add a separate Roam Plan interface with P1/P2/P3 navigation, expandable sections and clear live-data/illustrative-data states.
   - Add an entry link from the current dashboard.
   - Inspect the diff and document provider limitations and verification not performed.

## Acceptance checklist

- Existing app remains at `/`; planner is available at `/planner`.
- P1 allows arbitrary airport keyword lookup, flexible date windows, adults, children, and each child age.
- Candidate identity is date + outbound flight number + return date + inbound flight number.
- Adding a candidate starts tracking immediately; users can pause, resume, remove, and set a target. Active candidates refresh in the background at the configured interval.
- P2 history and lowest/closest summaries identify the associated itinerary and do not use mock values as live prices.
- P3 carries the P1 traveler composition, displays booking source and link, and distinguishes per-person estimates from verified party totals.
- Missing API credentials, provider errors, empty booking links, and infant ambiguity are visible and do not appear as successful prices.
- No API secrets, raw provider payloads, or private tokens are persisted or sent to the browser.
- No tests are run unless requested.
