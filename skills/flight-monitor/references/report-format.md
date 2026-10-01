# Persistence and reports v2

## Three layers

- `market_candidates`: every distinct eligible outbound with airline, local times, exact market-stage price, preference flags, token availability and triggers. Used for detection, not itinerary-price history.
- `itineraries`: last known complete outbound + inbound quotes. `itinerary_key` is normalized flight numbers joined with `+`, e.g. `OUT123+RET456`. Each record has its own `checked_at`, `observed_this_run`, observation status, returned price, previous itinerary price, historical low and change flags. Unqueried records retain their timestamp; newly observed records replace only their queried outbound's prior combinations.
- `itinerary_history.csv`: authoritative observed itinerary prices, partitioned by a hash of Hard Filters (`route_key`), currency and price scope. Append only freshly expanded quotes. Log disappeared combinations as `status=not_returned` with blank price, never as zero. Use only `status=observed` records for comparisons/lows. Do not copy market prices into this history.

## Files and coverage

`latest.json` schema v6 includes Skill version, execution mode, trip configuration, run time/status, source/validation, market candidates, itineraries, market lows and per-outbound refresh timestamps. It also reports attempted searches, account calls, quota before/after and account-wide observed usage delta. `options` remains a compatibility view of this run's fresh quotes; use `itineraries` for stored complete combinations.

Report `refreshed_outbounds`, `deferred_outbounds`, and `missing_required_outbounds`. `baseline_complete` means all configured main flights currently have stored return quotes and refresh timestamps within the effective interval, with no missing market flights/tokens. `refresh_complete` means every requested expansion completed this run without required-flight gaps. Neither proves Google Flights returned every saleable itinerary.

Record `planned_searches` after selecting expansions, alongside actual attempted `searches_used`. With the current trip's three main outbounds: Full Query or an overdue normal refresh plans up to four flight requests, an ordinary triggered monitor up to two, and a quiet monitor one. Account calls are separate and free of search quota. Keep `pending_deep_search` for requests deferred to future invocations.

`history.csv` preserves existing v1 rows/columns and appends current market/run observations. Old v1 return rows remain historical references; do not invent v2 refresh timestamps or baselines from them. `itinerary_history.csv` begins with explicitly observed v2 return prices. Preserve unknown CSV columns during header changes.

`last-run.json` records newest attempt, including errors and quota skips; latest and history retain the preceding valid run on search/parsing failure. Store sanitized error stage/type, known usage and attempted searches, never exception URLs containing secrets. Actions must retain diagnostics even after a failed query.

## Human report

State mode, trip dates/passengers/cabin, market airline coverage including preference mismatches, expanded outbound coverage and itinerary count, raw displayed prices with unknown scope, each quote's observation time, new lows/price changes, deferred/missing coverage, attempted searches versus Account API deltas, and remaining quota. Mark stale quotes and unconfirmed family prices/baggage explicitly. Say the refresh check runs on invocation when schedules are disabled.

Do not claim availability guarantees, verified family totals, baggage entitlement, full refresh completion, or quota billing facts that the recorded evidence does not establish.
