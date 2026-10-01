# Search policy v2

## Hard Filters versus Preferences

Hard Filters: route, outbound/return dates, passenger counts, cabin, nonstop, approved full-service airline codes, currency and market/locale. Validate both outbound and return segments against them. Keep all distinct eligible outbound flights in Market Scan, using the lowest displayed offer when the API returns duplicates of one flight.

Time cutoffs and airline preferences label/rank results locally. Never send `outbound_times` or `return_times`. A strict before cutoff excludes the exact boundary from preference matches but never removes that flight. Airport times are local. Combined preference is false if either leg fails, true if both pass, otherwise null.

## Execution modes

`full_query`:

1. Check account and perform one Market Scan.
2. Preserve all eligible outbound candidates, including time mismatches.
3. Take the configured main outbound flights' current departure tokens and expand each flight's eligible return options within quota.
4. Store every distinct outbound + inbound combination and its returned price; deduplicate identical itinerary keys by lowest displayed price.
5. Report baseline coverage, missing tokens/flights, and deferred expansions. Full Query does not imply every market outbound was expanded; its coverage is the configured main list.

`monitor_query` (default):

1. Perform one Market Scan and compare with the previous valid market snapshot for the same Hard Filters.
2. Deep Search triggers: below historical market low, >=5% drop from previous market price, new airline, or new outbound flight. Do not compare market-stage prices with return-stage itinerary prices.
3. Normally expand at most one triggered outbound. Retain other itinerary observations with their original checked time; do not create synthetic price-history rows from a market price.
4. Even if market prices are unchanged, refresh main outbounds after a configured 3–5 days (default four; reduced quota five). Without a prior refresh timestamp they are due. At normal quota, expand the main due flights within the full refresh cap. At reduced quota, refresh one and rotate oldest checks first on subsequent runs.
5. Compare each fresh itinerary price against its own last observed price and historical low in `itinerary_history.csv`, for the same route, currency and scope. Record drops, increases, new lows and new itineraries.

Substantial market drops have expansion priority, followed by oldest refresh timestamp, configured main-flight order and displayed price. Missing/deferred flights remain visible. A budget-limited refresh can stay overdue; never advance an outbound's refresh timestamp unless its query and parse succeeded.

Retain unserved triggers in `pending_deep_search`. Carry them into the next monitor run even when its market scan is unchanged; remove a pending outbound only after its expansion succeeds. This prevents a one-expansion cap from permanently losing simultaneous new-flight signals. A missing token keeps the request deferred.

Refresh is checked on execution, with no autonomous scheduling. If no queries run for several days, prices cannot be observed during that gap. A return combination absent from a successfully expanded outbound is `not_returned`, not a zero price or guaranteed sold-out flight. Unqueried outbounds' return combinations retain their previous timestamp; absence from the market scan alone is not proof of a price or availability change.

## Quota

Use safe Account API fields: `this_month_usage`, `total_searches_left`, `plan_searches_left`, renewal date. Account calls do not consume search quota: [official account documentation](https://serpapi.com/account-api). Departure tokens and parameters: [Google Flights API](https://serpapi.com/google-flights-api).

| Monthly usage | Policy |
| --- | --- |
| <200 | One market scan; normal monitor maximum one triggered expansion; full/due refresh up to configured main cap |
| 200–224 | Full/deep/due refresh limited to one outbound per run; interval extended to five days |
| 225–239 | Market scan only; mark refreshes deferred |
| >=240 or no remaining searches | Stop nonessential queries; this executor makes zero flight requests |

Read account before searching, after market and after every expansion. Before each further request use the larger of actual usage and initial usage plus attempted searches, and the smaller of actual remaining and initial remaining minus attempts. Reevaluate tier during Full Query; a run crossing 200 or 225 reduces/stops expansion. Account failure stops the run; no automatic paid retries. Account deltas cover all consumers of the key and can lag, so report attempted requests separately from observed account changes.

## Price semantics and failure

Price is the raw displayed API fare. Do not infer per-person/family scope or calculate price × passenger count. Maintain unknown scope, null family total and unknown baggage until independently verified. Preserve extension text only as unverified evidence if needed; it does not establish baggage entitlement. The v2 executor does not trigger family-budget comparisons.

Finish all flight parsing before writing snapshots or histories. API/network/malformed response failure, including a failure late in Full Query, preserves the whole previous valid run and writes sanitized `last-run.json` diagnostics. A documented empty response is a successful empty observation. Never bypass CAPTCHA or anti-bot blocks.

## Isolated Market Scan deep_search experiment

SerpApi's `deep_search=true/false` controls market result precision/performance. It is not the departure-token Deep Search described above. See [official parameters](https://serpapi.com/google-flights-api). Production full/monitor queries continue to omit this optional parameter and retain their existing default.

Run `python scripts/flight_market_test.py --deep-search false` or `--deep-search true` for one Market Scan. Use `--compare` to run false then true sequentially with the same trip/configuration and all other API parameters identical. The dedicated `flight-market-test.yml` workflow offers `single_scan` with a boolean `deep_search`, or `ab_comparison`. Manual dispatch only; no schedule/push trigger.

Each variant makes exactly one flight request, never expands departure tokens, and reads Account API before/after. An A/B pair plans at most two flight requests and four free Account API calls. Respect quota preservation at >=240 or no remaining credit; abort/defer the second variant if the actual or conservative estimated usage reaches that boundary. No paid retries. The experimental flight timeout is 120 seconds; production remains 45 seconds.

Record eligible distinct flight count, raw offer count, every eligible flight's returned price/local preference, measured client response seconds, safe server metadata, and quota before/after. Time only the market HTTP response/JSON decode, excluding Account API and local preference evaluation. Do not label sequential or cached observations as a guaranteed causal improvement, exact browser match, or final billing charge. Do not force `no_cache`; record metadata so cache effects remain visible.

Experiments write only below `travel/nagoya/flights/experiments/`, with a unique run directory. Actions retain JSON as an artifact and never commit any monitoring data. Hash latest, history, itinerary_history and last-run before/after to verify isolation. Experiment failures also go only into experiment reports, never production last-run. An incomplete pair has no completed comparison.
