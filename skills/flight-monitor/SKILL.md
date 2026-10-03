---
name: flight-monitor
description: Build full round-trip itinerary baselines and monitor fare changes within an API budget, separating market signals from itinerary price history and mandatory filters from preferences. Use for flight fare baselines, recurring monitoring, or adapting a monitor to another trip.
---

# Flight Monitor v2

Load route, dates, passengers, cabin, airline eligibility, market/currency, time preferences, main outbound flights and budget from the trip configuration. Keep trip-specific values outside this Skill. The current executor is `scripts/nagoya_flight_monitor.py`, with trip configuration under `travel/nagoya/flight-monitor.json`.

Read [search-policy.md](references/search-policy.md) before querying or changing execution. Read [report-format.md](references/report-format.md) when persisting or presenting results.

Use `full_query` to establish the main outbound flights' return combinations; use `monitor_query` for one default market scan, conditionally expanding return flights or refreshing overdue itineraries. A market fare is a detection signal. Only the price of an explicitly expanded outbound + inbound combination belongs in itinerary price history.

For an explicitly requested SerpApi `deep_search` test, use the isolated `scripts/flight_market_test.py` entry point and the experiment section of [search-policy.md](references/search-policy.md). This API parameter applies to Market Scan and is distinct from departure-token return expansion. Do not change production defaults or write experiment observations into baseline/history.

For an explicitly requested passenger price-scope experiment, use `scripts/price_scope_experiment.py` with its separate trip configuration. Pin the same itinerary using `selected_flights_json`, vary only passenger counts, and compare uniquely matched seller/fare options. Follow the price-scope section of [search-policy.md](references/search-policy.md); never promote an experimental inference into production price scope automatically.

Hard Filters define API eligibility. Evaluate time Preferences locally; retain eligible flights even if they fail a Preference. Unknown return times remain unknown. Never enable business-cabin queries as routine monitoring.

Use actual Account API usage and remaining quota, with conservative bounds for delayed counters. Defer deep/full refreshes when quota requires it; report missing, deferred and stale coverage instead of claiming a full baseline.

Never multiply price by passenger count. Maintain `price_scope: unknown`, `family_total_twd: null`, and `baggage_status: unknown` until independently verified. Do not use an unverified fare as a family-budget claim.

Extra Booking Options verification is allowed only for a fresh itinerary near the configured price target, a genuine historical new low, a drop at least the configured threshold, or an explicitly requested purchase itinerary. New airlines/flights and initial baselines alone do not authorize verification. Limit it to one additional search per run and obey quota. Confirm both selected legs and the exact displayed price for the configured two-adult/two-child party before marking that specific quote `family_total`; store literal seller-specific baggage evidence separately. Never backfill old quotes or apply one itinerary's verification to others.

On API/parsing failure preserve the last valid snapshot and histories. Save a separate sanitized error including stage and attempted searches. Never persist keys, departure tokens, credential URLs, account identity or raw account responses.

Use authorized data sources. Stop at CAPTCHA or anti-bot blocks without bypass attempts. Respect the user's authorization for quota usage and remote writes. Periodic refresh checks happen when a query runs; they do not authorize enabling a schedule.

## Scheduled execution and report delivery

Keep execution, monitoring logic, and report delivery as separate responsibilities:

- This Skill defines query policy, persistence, and report formatting. Reading or invoking the Skill in a ChatGPT scheduled task does **not** prove that the remote flight query executed.
- GitHub Actions is the authoritative scheduled executor for the current repository implementation. The production workflow is `.github/workflows/nagoya-flight-monitor.yml`.
- For the Nagoya production case, the GitHub Actions schedule runs daily at 09:50 Asia/Taipei (01:50 UTC). Scheduled workflow events must explicitly resolve to `monitor_query`; do not rely on `workflow_dispatch.inputs.mode`, because scheduled events do not provide that input.
- ChatGPT scheduled tasks are the presentation layer: after the GitHub run, read the repository's current `latest.json`, `last-run.json`, and itinerary history and render the Human report defined in `references/report-format.md`.
- Produce a report on every scheduled presentation run, including runs with no meaningful fare change. If GitHub data did not advance as expected, report that execution/data freshness problem instead of presenting retained quotes as today's fresh prices.
- A ChatGPT task invocation proves only that the presentation task ran. A GitHub Actions run plus updated run evidence proves that the flight monitor executed. Always check repository timestamps/status before calling a quote fresh.
- Do not duplicate the production fare query in the ChatGPT task merely to compensate for a missing GitHub run. Diagnose or repair the execution chain instead, preserving GitHub as the monitoring system of record.

