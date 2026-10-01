---
name: flight-monitor
description: Monitor flight fares within a limited API budget, distinguish mandatory filters from preferences, compare market snapshots, and report verified price scope. Use for recurring fare monitoring or adapting an existing flight monitor to another route.
---

# Flight Monitor

Load the trip's existing configuration for route, dates, passengers, cabin, market, airline eligibility, preferences and price target. Keep trip-specific values outside this Skill. The current executor is `scripts/nagoya_flight_monitor.py`; its trip configuration lives under `travel/nagoya/flight-monitor.json`.

Read [search-policy.md](references/search-policy.md) before searching or changing an executor. Read [report-format.md](references/report-format.md) when persisting or presenting results.

Use mandatory Hard Filters in the API request. Evaluate Preferences locally and retain all eligible market candidates, including preference mismatches. An unknown return time is unknown, not a failed preference.

Start with one Market Scan. Compare like-for-like observations and use a returned departure token for at most one Deep Search when the policy permits. Check actual account usage and remaining quota; do not infer quota from this monitor's history alone. Business cabin searches require a separate explicit request.

Store the API's displayed price without assuming per-person or family-total semantics, multiplying by passenger count, or claiming baggage inclusion. A family target comparison requires independently verified price scope and matching passengers/currency.

Keep the last valid snapshot on API or parsing failure. Record a separate sanitized error with stage, timestamp, attempted searches and known quota. Never log keys, token URLs, account identity or raw account responses.

Use authorized data sources. Stop on CAPTCHA or anti-bot blocks; do not circumvent them. Respect the user's authorization for paid usage and remote writes. Do not enable recurring schedules unless explicitly requested.
