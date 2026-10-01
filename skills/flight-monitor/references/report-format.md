# Persistence and reports v2

## Three layers

- `market_candidates`: every distinct eligible outbound with airline, local times, exact market-stage price, preference flags, token availability and triggers. Used for detection, not itinerary-price history.
- `itineraries`: last known complete outbound + inbound quotes. `itinerary_key` is normalized flight numbers joined with `+`, e.g. `OUT123+RET456`. Each record has its own `checked_at`, `observed_this_run`, observation status, returned price, previous itinerary price, historical low and change flags. Unqueried records retain their timestamp; newly observed records replace only their queried outbound's prior combinations.
- `itinerary_history.csv`: authoritative observed raw itinerary prices, partitioned by a hash of Hard Filters (`route_key`) and currency. Both unknown and verified family-total labels participate in raw-price comparisons. Append only freshly expanded price observations. Log disappeared combinations as `status=not_returned` with blank price, never as zero. Use only `status=observed` records for comparisons/lows. Do not copy market prices into this history.

## Files and coverage

`latest.json` schema v7 includes Skill version, execution mode, trip configuration, run time/status, source/validation, market candidates, market lows, stored itineraries, per-outbound refresh timestamps and conditional booking verification. It reports attempted searches, account calls, quota before/after and account-wide observed usage delta. `options` remains a compatibility view of this run's fresh quotes; use `itineraries` for stored complete combinations.

Report `refreshed_outbounds`, `deferred_outbounds`, and `missing_required_outbounds`. `baseline_complete` means all configured main flights currently have stored return quotes and refresh timestamps within the effective interval, with no missing market flights/tokens. `refresh_complete` means every requested expansion completed this run without required-flight gaps. Neither proves Google Flights returned every saleable itinerary.

Record `planned_searches` after selecting expansions, alongside actual attempted `searches_used`. Full Query or an overdue refresh uses one market request plus the permitted outbound expansions from trip configuration and quota policy; a quiet monitor uses one market request. Account calls are separate and free of search quota. Keep `pending_deep_search` for requests deferred to future invocations.

Conditional Booking Options adds at most one flight request to those counts. Report `booking_verification_checks`: itinerary key, trigger reasons, result/error/deferred reason and Account before/after. A verified row stores `price_verification` and optional `baggage_verification`, including seller, fare fields, request passengers/currency, original quote time and verification time. Baggage status `booking_option_verified` means the chosen seller supplied literal evidence; never invent weight/per-person scope. A purchase check on a retained quote appends `record_type=verification`, `status=verified`, not a new `observed` price. Old history records are preserved without backfilling. Fresh itinerary quotes must be verified again.

`history.csv` preserves existing v1 rows/columns and appends current market/run observations. Old v1 return rows remain historical references; do not invent v2 refresh timestamps or baselines from them. `itinerary_history.csv` begins with explicitly observed v2 return prices. Preserve unknown CSV columns during header changes.

`last-run.json` records newest attempt, including errors and quota skips; latest and history retain the preceding valid run on search/parsing failure. Store sanitized error stage/type, known usage and attempted searches, never exception URLs containing secrets. Actions must retain diagnostics even after a failed query.

## Human report

Use this fixed report layout for every trip. Read route, dates, passengers, currency, target and airline names from trip configuration and stored observations; never hardcode a trip's target amount, dates, route or flight numbers into these rules. Briefly state the trip context before the tables.

### Main table: 完整 itinerary 價格 Top 5

Select complete, valid itineraries from `latest.json`: both legs and a positive finite `displayed_price_twd` must be present. Sort by `displayed_price_twd` ascending; break ties by `itinerary_key` for stable presentation. Display at most five, or all available when fewer than five. If none are available, say there are no complete itinerary quotes; never substitute market prices.

Top 5 is only a presentation filter. Preserve every valid itinerary in `latest.json` and every valid observed itinerary price in `itinerary_history.csv`, including those outside the table. Ranking must not delete stored quotes, change monitoring coverage, or cause any additional API request. Existing observation/retention rules still apply: do not fabricate fresh history rows from retained quotes.

Use exactly this column order:

| 排名 | 航空公司 | 去程 | 回程 | 目前價格 | 漲跌 | 價格狀態 | 監控低點 | 時間偏好 | 資料時間 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

- **排名**: 1 through 5 in the sorted order.
- **航空公司**: use the trip's airline display-name mapping or an observed name; do not guess missing names. For the same airline on both legs show its name once. For mixed airlines show outbound airline, a line break, then `× ` followed by inbound airline. In Markdown use `<br>` for the line break. Determine each leg's airline from its own code, not the outbound name alone.
- **去程 / 回程**: `航班號 HH:MM → HH:MM`, with normalized flight number and each airport's local departure/arrival time. Missing times are `待確認`; do not invent them.
- **目前價格**: the exact stored `displayed_price_twd`, formatted `NT$` with thousands separators. Never multiply by passenger count or substitute a market-stage fare. This is an API displayed price unless the specific fresh quote has valid Booking Options verification.
- **漲跌**: compare the same itinerary's immediately preceding valid observed raw displayed price for the same `route_key` and currency. Verification-only rows, missing/not-returned records and retained copies are not previous price observations. Calculate `delta = current - previous` and percentage `delta / previous × 100`, rounded to one decimal. Show decreases as `↓ NT$2,100 (-3.2%)`, increases as `↑ NT$1,500 (+2.4%)`, unchanged prices as `NT$0 (0.0%)`, and no valid previous price as `—`. For a retained quote use its original observation's comparison; do not compare the retained copy to itself.
- **價格狀態**: classify the raw displayed price against `target = trip_config.family_target_twd` using the mutually exclusive boundaries below. Display the signed amount difference from target, for example `偏高 +NT$13,064`; use `-NT$…` below target and `NT$0` at target. If the configured target is missing or invalid, show `目標待設定`; never supply a fallback amount.

| Displayed price `p` | 價格狀態 |
| --- | --- |
| `p <= target` | 達標 |
| `target < p <= target × 1.10` | 接近目標 |
| `target × 1.10 < p <= target × 1.20` | 略高 |
| `target × 1.20 < p <= target × 1.40` | 偏高 |
| `p > target × 1.40` | 高於目標 |

If `price_scope != family_total`, append **依 API 顯示價格暫估** inside the price-status cell. Only a fresh quote (`observed_this_run=true`) with successful Booking Options evidence matching that exact quote, itinerary, configured party and currency may support a formal family-budget judgment. A retained previously verified quote is historical evidence: label its status `依 API 顯示價格暫估（既有驗證，非本次 fresh quote）` and do not present it as a freshly verified family budget. Unknown or missing verification remains unknown; never backfill evidence or extrapolate one itinerary's verification to others.

- **監控低點**: the same itinerary's lowest valid historical raw displayed price, including the current valid observation, for the same `route_key` and currency. Use only valid `status=observed` prices in `itinerary_history.csv`, regardless of unknown/family-total labels; never use market fares, verification-only records, missing prices or other itineraries. Show `—` if no valid low is available.
- **時間偏好**: map the two local preference flags exactly as follows. Incomplete return information or an unknown flag means `待確認`; retain flights that fail a preference.

| Outbound preference | Inbound preference | 時間偏好 |
| --- | --- | --- |
| true | true | 符合 |
| false | true | 去程晚 |
| true | false | 回程晚 |
| false | false | 去回程皆晚 |
| unknown / incomplete | any, or vice versa | 待確認 |

- **資料時間**: use each itinerary's own `checked_at`, displayed in the user's timezone with date, time and timezone/offset. Never substitute report execution time, market scan time or Booking Options verification time. Mark unrefreshed retained quotes `保留報價（非本次更新）`; additionally mark overdue quotes `stale` when their age exceeds the effective configured refresh interval. Show the original timestamp so age is visible. A retained quote still participates in Top 5 but is not current availability evidence.

### Independent table: Market Scan 補充表

After the main table, show eligible `market_candidates` with a market signal but no stored valid complete itinerary for that outbound. Compare against **all** stored complete itineraries, not just Top 5; an outbound whose itinerary ranks lower than five must not appear as unexpanded. If none qualify, say `無尚未展開的市場航班`.

| 航空公司 | 去程 | API 顯示價格 | 時間偏好 | 狀態 |
| --- | --- | --- | --- | --- |

Use the same airline naming and outbound time format. Show the exact raw market-stage price. Outbound preference is `符合`, `去程晚`, or `待確認`; this is an outbound-only assessment, not the complete itinerary preference. Status must state `市場訊號／尚未展開完整 itinerary` and any recorded deferred or missing-token reason. Keep this table separate from itinerary Top 5. Market prices are not complete round-trip quotes, must never enter itinerary history, and must not prompt extra API calls merely to populate this table.

### Brief status below the tables

- Market Scan and itinerary refresh: state success/error/skip, mode, actual expanded outbounds and coverage, with attempted market/return/booking request counts and total `searches_used`; Account calls are separate. Use recorded run status, not an assumption of completion.
- Booking Options: state verified/not triggered/deferred/failed/price not matched, identify affected itineraries and verification times, and distinguish price verification from seller-specific baggage verification. Missing baggage remains unknown; do not invent entitlements.
- Monthly quota: show Account API observed usage and remaining quota, tier, and before/after delta when available. Counter changes may lag or include other consumers; attempted searches do not guarantee a billed delta. Missing account data is `未取得`, not zero.
- If present, list deferred, stale and missing coverage briefly, including relevant itinerary/outbound keys. Disclose use of the preceding valid snapshot after a failed run and keep its original quote times. Refresh checks occur only on invocation when schedules are disabled.

Do not claim availability guarantees, freshly verified family totals, baggage entitlement, full refresh completion, or quota billing facts that the recorded evidence does not establish. Generating this report reads existing records only and never authorizes an API query.

## Experimental A/B report

Separate experiment `results.json` records `single_scan` or `ab_comparison`, a hash and safe copy of shared query conditions, planned/attempted searches and Account-call count. Each variant has the explicit boolean `deep_search`, request/parse status, raw offers and eligible distinct flight count, exact flight prices, response time seconds, safe search metadata, quota before/after and observed account-wide delta. Keep unknown price scope, null family total and unknown baggage.

For successful A/B pairs, report added/removed flight numbers, common-flight price differences and response-time difference (true minus false). Flag sequential timing, caching and delayed quota-counter limitations. Failed or quota-limited pairs must not claim a complete comparison. Store sanitized errors and SHA-256 checks showing whether all four production monitoring files stayed unchanged. These hashes are evidence of isolation, not additional writes to the baseline.

The experiment artifact is independent of all formal snapshots/history. It is suitable for deciding whether to change a production default later; running the experiment does not authorize that change.
