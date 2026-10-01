# Report and persistence

`latest.json` is the last valid market observation. Include schema version, checked time, trip configuration, status, source/validation state, `searches_used` (attempted flight requests), compatibility `api_searches_used`, account-call count, safe quota before/after, and `actual_usage_delta` (account-wide). Distinguish market-only from market-plus-return.

Store every eligible outbound in `market_candidates` with airline/code, flight, airport-local times, exact displayed price, unknown price scope, null family total, per-leg preference evaluation, token availability (never the token itself), and deep triggers. Store newly checked return combinations in `options`. An empty options list may simply mean no deep search. Maintain historical market lows independently from round-trip prices.

`history.csv` appends market observations as `record_type=market` and return pairs as `round_trip`, or an empty-observation `run` row. Retain prior rows during header migration; old unknown columns should be retained. Record searches, quota tier/usage/remaining and preference decisions for each current row. Do not backfill old rows with guessed family totals or budget results.

`last-run.json` reports the newest attempt, including errors or quota skips, while latest retains its earlier valid timestamp. Errors include error type/stage and sanitized explanation; never include secret-bearing exception URLs. Workflow must persist/upload this diagnostic even when execution exits nonzero, and still surface the failed job.

Human reports state:

- Route/date/passengers/cabin and observation time.
- Market airlines observed, including preference mismatches.
- Displayed prices and explicit unknown/verified scope; target comparison unavailable when unverified.
- Outbound/inbound/combined preference true, false or unknown.
- Deep lookup reason or why it was skipped; market scope and return completeness limits.
- Attempted searches, account calls, before/after monthly usage/remaining and account-wide delta.
- Failure/staleness or quota preservation, and unresolved verification.

Do not claim a sale price, availability guarantee, family total, baggage inclusion or completed query when the evidence does not support it.
