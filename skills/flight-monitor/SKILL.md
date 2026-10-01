---
name: flight-monitor
description: Build full round-trip itinerary baselines and monitor fare changes within an API budget, separating market signals from itinerary price history and mandatory filters from preferences. Use for flight fare baselines, recurring monitoring, or adapting a monitor to another trip.
---

# Flight Monitor v2

Load route, dates, passengers, cabin, airline eligibility, market/currency, time preferences, main outbound flights and budget from the trip configuration. Keep trip-specific values outside this Skill. The current executor is `scripts/nagoya_flight_monitor.py`, with trip configuration under `travel/nagoya/flight-monitor.json`.

Read [search-policy.md](references/search-policy.md) before querying or changing execution. Read [report-format.md](references/report-format.md) when persisting or presenting results.

Use `full_query` to establish the main outbound flights' return combinations; use `monitor_query` for one default market scan, conditionally expanding return flights or refreshing overdue itineraries. A market fare is a detection signal. Only the price of an explicitly expanded outbound + inbound combination belongs in itinerary price history.

For an explicitly requested SerpApi `deep_search` test, use the isolated `scripts/flight_market_test.py` entry point and the experiment section of [search-policy.md](references/search-policy.md). This API parameter applies to Market Scan and is distinct from departure-token return expansion. Do not change production defaults or write experiment observations into baseline/history.

Hard Filters define API eligibility. Evaluate time Preferences locally; retain eligible flights even if they fail a Preference. Unknown return times remain unknown. Never enable business-cabin queries as routine monitoring.

Use actual Account API usage and remaining quota, with conservative bounds for delayed counters. Defer deep/full refreshes when quota requires it; report missing, deferred and stale coverage instead of claiming a full baseline.

Never multiply price by passenger count. Maintain `price_scope: unknown`, `family_total_twd: null`, and `baggage_status: unknown` until independently verified. Do not use an unverified fare as a family-budget claim.

On API/parsing failure preserve the last valid snapshot and histories. Save a separate sanitized error including stage and attempted searches. Never persist keys, departure tokens, credential URLs, account identity or raw account responses.

Use authorized data sources. Stop at CAPTCHA or anti-bot blocks without bypass attempts. Respect the user's authorization for quota usage and remote writes. Periodic refresh checks happen when a query runs; they do not authorize enabling a schedule.
