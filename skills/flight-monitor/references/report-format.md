# Persistence and reports v2

## Three layers

- `market_candidates`: every distinct eligible outbound with airline, local times, exact market-stage price, preference flags, token availability and triggers. Used for detection, not itinerary-price history.
- `itineraries`: last known complete outbound + inbound quotes. `itinerary_key` is normalized flight numbers joined with `+`, e.g. `OUT123+RET456`. Each record has its own `checked_at`, `observed_this_run`, observation status, returned price, previous itinerary price, historical low and change flags. Unqueried records retain their timestamp; newly observed records replace only their queried outbound's prior combinations.
- `itinerary_history.csv`: authoritative observed raw itinerary prices, partitioned by a hash of Hard Filters (`route_key`) and currency. Both unknown and verified family-total labels participate in raw-price comparisons. Append only freshly expanded price observations. Log disappeared combinations as `status=not_returned` with blank price, never as zero. Use only `status=observed` records for comparisons/lows. Do not copy market prices into this history.

## Files and coverage

`latest.json` schema v7 includes Skill version, execution mode, trip configuration, run time/status, source/validation, market candidates, market lows, stored itineraries, per-outbound refresh timestamps and conditional booking verification. It reports attempted searches, account calls, quota before/after and account-wide observed usage delta. `options` remains a compatibility view of this run's fresh quotes; use `itineraries` for stored complete combinations.

Report `refreshed_outbounds`, `deferred_outbounds`, and `missing_required_outbounds`. `baseline_complete` means all configured main flights currently have stored return quotes and refresh timestamps within the effective interval, with no missing market flights/tokens. `refresh_complete` means every requested expansion completed this run without required-flight gaps. Neither proves Google Flights returned every saleable itinerary.

Record `planned_searches` after selecting expansions, alongside actual attempted `searches_used`. With the current trip's three main outbounds: Full Query or an overdue normal refresh plans up to four flight requests, an ordinary triggered monitor up to two, and a quiet monitor one. Account calls are separate and free of search quota. Keep `pending_deep_search` for requests deferred to future invocations.

Conditional Booking Options adds at most one flight request to those counts. Report `booking_verification_checks`: itinerary key, trigger reasons, result/error/deferred reason and Account before/after. A verified row stores `price_verification` and optional `baggage_verification`, including seller, fare fields, request passengers/currency, original quote time and verification time. Baggage status `booking_option_verified` means the chosen seller supplied literal evidence; never invent weight/per-person scope. A purchase check on a retained quote appends `record_type=verification`, `status=verified`, not a new `observed` price. Old history records are preserved without backfilling. Fresh itinerary quotes must be verified again.

`history.csv` preserves existing v1 rows/columns and appends current market/run observations. Old v1 return rows remain historical references; do not invent v2 refresh timestamps or baselines from them. `itinerary_history.csv` begins with explicitly observed v2 return prices. Preserve unknown CSV columns during header changes.

`last-run.json` records newest attempt, including errors and quota skips; latest and history retain the preceding valid run on search/parsing failure. Store sanitized error stage/type, known usage and attempted searches, never exception URLs containing secrets. Actions must retain diagnostics even after a failed query.

## Human report

State mode, trip dates/passengers/cabin, market airline coverage including preference mismatches, expanded outbound coverage and itinerary count, raw displayed prices with unknown scope, each quote's observation time, new lows/price changes, deferred/missing coverage, attempted searches versus Account API deltas, and remaining quota. Mark stale quotes and unconfirmed family prices/baggage explicitly. Say the refresh check runs on invocation when schedules are disabled.

Do not claim availability guarantees, verified family totals, baggage entitlement, full refresh completion, or quota billing facts that the recorded evidence does not establish.

## Experimental A/B report

Separate experiment `results.json` records `single_scan` or `ab_comparison`, a hash and safe copy of shared query conditions, planned/attempted searches and Account-call count. Each variant has the explicit boolean `deep_search`, request/parse status, raw offers and eligible distinct flight count, exact flight prices, response time seconds, safe search metadata, quota before/after and observed account-wide delta. Keep unknown price scope, null family total and unknown baggage.

For successful A/B pairs, report added/removed flight numbers, common-flight price differences and response-time difference (true minus false). Flag sequential timing, caching and delayed quota-counter limitations. Failed or quota-limited pairs must not claim a complete comparison. Store sanitized errors and SHA-256 checks showing whether all four production monitoring files stayed unchanged. These hashes are evidence of isolation, not additional writes to the baseline.

The experiment artifact is independent of all formal snapshots/history. It is suitable for deciding whether to change a production default later; running the experiment does not authorize that change.
