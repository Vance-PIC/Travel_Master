# Search policy

## Hard Filters and Preferences

Hard Filters define eligibility: route, travel dates, passenger counts, cabin, nonstop requirement, approved full-service airline codes, currency and country/locale. API adapters must enforce these and validate returned segments. A market result is an outbound candidate, not a confirmed round-trip pair.

Preferences rank or label eligible results: departure/arrival time cutoffs, airline preference and target budget. Never translate time preferences into API `outbound_times` or `return_times`, or delete legal airlines because of them. Use airport-local times. Boundary comparisons are strictly before the configured cutoff. Record true/false/null per leg; combined preference is false if either fails, true only if both pass, otherwise null.

## Market Scan and Local preference evaluation

Read the account before searching. One round-trip Economy market request is the default. Parse both best and other flight groups; retain every eligible candidate without an arbitrary shortlist. Apply outbound preference locally; inbound preference stays null until a return segment is retrieved. Do not routinely search business class.

## Deep Search triggers

Compare the same configured trip and outbound flight, with the same displayed-price basis and unknown scope treated only as a displayed-price observation. Never compare market prices with a return-stage price as if interchangeable.

- New low: below the maintained historical market low for that flight.
- Price drop: at least the configured fraction (default 5%) below the preceding market observation for that flight.
- Near family target: verified family total at or below target plus the configured margin (default 10%). Unknown scope disables this trigger; do not substitute raw API price.
- New airline or outbound flight since the previous valid market snapshot.
- Initial baseline: only when no valid prior market exists; clearly label it.

Use the token from the current result, with the original hard parameters, for at most one additional request. Prioritize a substantial drop, then lowest displayed price among triggered candidates. Preserve all other market candidates. Validate return hard filters independently; mixed eligible full-service carriers are permitted. Do not claim return completeness from a single deep lookup.

## Quota policy

Use SerpApi Account API `this_month_usage`, `total_searches_left`, `plan_searches_left`, and renewal date. Persist only these safe fields. Account calls are free and not counted as searches: [official documentation](https://serpapi.com/account-api). Search parameters and departure token behavior: [Google Flights API](https://serpapi.com/google-flights-api).

| Actual monthly usage | Policy |
| --- | --- |
| <200 | One market scan; at most one triggered deep search |
| 200–224 | Deep search only for >=5% drop or verified near-target total |
| 225–239 | Market scan only |
| >=240, or no remaining searches | Preserve quota; zero flight requests |

Recheck account after market and after deep search. For the next request use the more conservative of actual account values and starting usage plus attempted requests, so delayed counters cannot cross a boundary. Missing/invalid Account API data stops the run. No automatic paid retries. Concurrent users of the same key can affect account deltas; serialize this monitor and label the delta as account-wide, not exclusive billing proof.

## Failure and price semantics

Keep `price_scope: unknown` and `family_total_twd: null` until verified from a documented source for the same itinerary and passenger set. Never multiply displayed fare by passenger count. Baggage text is unverified unless separately confirmed.

API/network/malformed payload failure preserves latest and history. A documented empty result is a successful empty observation. A deep failure fails the run and preserves the previous snapshot rather than publishing partial data as complete. Persist a separate sanitized last-run record, including failures and quota skips. Stop at CAPTCHA/anti-bot responses without bypass attempts.
