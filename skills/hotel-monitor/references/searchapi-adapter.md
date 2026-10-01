# SearchAPI manual capability verification

Provider: **searchapi.io**, independent of the flight monitor's SerpApi.com account,
`SERPAPI_KEY`, and allowance. Hotel authentication uses environment variable
`SEARCHAPI_KEY` in the Authorization Bearer header. Never put a key in config or URLs.

Official contracts:
- https://www.searchapi.io/docs/google-hotels-api
- https://www.searchapi.io/docs/google-hotels-property-api

The adapter is `scripts/hotel_searchapi.py`. It first discovers hotels with
`google_hotels`, then requests details with `google_hotels_property` using the
discovered property identifier. Both calls retain dates, adults, child ages and
query currency. There is no documented room-count filter; the requested party
does not prove that a quoted room accepts all guests.

Local invocation (requires injected key):
`python scripts/hotel_searchapi.py --live --output work/hotel-api-verification.json`
Use `--monitor airport-candidate` for the candidate capability check.
GitHub Actions offers **Hotel API verification**, manual dispatch only, defaulting
to the booked hotel. No schedule, booking, notification, or repository write occurs.
Every attempted search counts toward the five-request cap, including failures;
there are no retries or pagination. This local cap does not establish account
credits or the provider's billing rules. Check available credits before dispatch.

Outputs are verification artifacts, never `latest`, `history` or `last-run`.
Only actual `rooms` / `rates` price fields are retained. Hotel and OTA aggregate
prices cannot become a room price. Policies and prices are not inherited from an
offer into a room. Missing total prices remain null; nightly prices are not
multiplied to fabricate a total. Tracking URLs and property tokens are omitted.
Currency is labelled query_currency, pending verification of response semantics.

This first integration deliberately leaves every room match uncertain and every
comparison pending_confirmation. It proves response capability, not room
equivalence. Candidate rooms are unqualified pending occupancy, size, beds,
smoking and geography evidence. Baseline 77,836 and threshold 70,000 retain unknown
currency and price scope even though the query currency is JPY. No alert is eligible.

Formal executor and Stage evaluators now exist: see [executor.md](executor.md).
This capability-verification entry point remains isolated. Source ID/address and
room evidence mapping still require actual evidence; account allowance is not
inferred from request counts. Scheduling remains disabled.

Engine localization overrides are configured in `api.engine_parameters`. A null
`hl` omits the optional field for `google_hotels_property`, while discovery keeps
`api.hl=en`. Run 36847823093 accepted discovery but rejected property `hl=en`
with HTTP 400, despite the documented default. Omission uses the provider default;
live property success remains unverified. Dates, party and currency are preserved.
