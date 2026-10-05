# Unified hotel monitor request (schema version 1)

The hotel executor accepts one request envelope. `monitor_id` loads a saved monitor;
`input` recursively overrides its allowed runtime fields. Without `monitor_id`,
`input` is a complete, stage-specific hotel request. Lists and nulls replace the
saved value. The saved config is not mutated by `none` or `run`.

```json
{
  "schema_version": 1,
  "monitor_id": "airport-candidate",
  "input": {"stay": {"check_in": "2027-07-18", "check_out": "2027-07-19"}},
  "persist_policy": "run"
}
```

For saved monitors, runtime `input` may contain `stay`, `party`, `hard_filters`,
and `preferences`. It cannot change the monitor ID, Stage, booked hotel identity,
or booking baseline. A complete ad-hoc `input` needs `stage`, `stay`, `party`, and
Stage 1 `hard_filters.location.anchor`, or Stage 2 hotel identity, room and booking
baselines, and alert. The party must include adult/child counts and child ages.

The canonical `config_hash` is SHA-256 of UTF-8 JSON for the effective request,
with sorted keys, compact separators and no NaN. Each attempted query saves or
returns its `effective_request` and hash; successful snapshots save both. The
existing `comparison_key` and `config_fingerprint` remain for compatibility.

| `persist_policy` | Behavior |
| --- | --- |
| `none` | Default for ad-hoc. Return the result and metadata; do not save monitor records. GitHub Actions retains the JSON result as an artifact. |
| `run` | Default for saved. An unchanged saved request uses the existing monitor directory. Overrides and ad-hoc runs use a unique `persistence_root/_runs/<id>/` directory, leaving scheduled latest/history untouched. |
| `monitor` | Requires a saved monitor, a nonempty override, `--allow-monitor-update`, and a matching full `--confirm-config-hash`. The config file changes only after a successful query; the run is saved separately. The workflow does not pass these flags, so dispatch cannot permanently update config. |

Run a request from the repository root:

```sh
python scripts/hotel_executor.py resolve-request --request-file request.json
python scripts/hotel_executor.py run-request --request-file request.json
```

`resolve-request` validates and prints the effective request and full hash
without querying or writing data. Use that hash for an explicitly approved
`monitor` update with `--allow-monitor-update --confirm-config-hash <hash>`.

`--allow-query` retains its existing one-run query authorization semantics. The
`request.json` file is the CLI boundary for a future hotel MCP. Manual workflow
dispatch also accepts the same envelope as `request_json`. The existing
`--monitor` dispatch and daily 01:50 UTC (09:50 Asia/Taipei) schedule keep using
their original commands. `monitor` persistence is available only through the
explicit local CLI confirmation path; review the resulting config diff before
committing it.
