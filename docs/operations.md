# Operations

## Prometheus metrics

Perevoditarr exposes Prometheus-style metrics at `GET /metrics` (plain text, exposition
format). The endpoint reports intents by state, dispatch throughput, rail posture,
library sync durations, and telemetry stream health.

### Exposed metrics

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `perevoditarr_intents` | gauge | `state` | Count of intents in each lifecycle state. |
| `perevoditarr_dispatches_total` | counter | (none) | Total Bazarr translate dispatches to date. |
| `perevoditarr_dispatches_recent` | gauge | `window` (`hour`, `day`) | Dispatches within the last hour and last day. |
| `perevoditarr_rail_paused` | gauge | rail scope | Rail pause flag (`1` = paused). |
| `perevoditarr_rail_breaker_state` | gauge | instance scope | Circuit breaker state: `0` closed, `1` half_open, `2` open (emitted for instance-scoped rails). |
| `perevoditarr_sync_duration_seconds` | gauge | `instance` | Duration of the last completed library sync per instance. |
| `perevoditarr_telemetry_stream_up` | gauge | `instance`, `stream`, `state` | Telemetry stream liveness (`1` = live on websocket, `0` = on polling fallback). |

### Sample scrape config

Add a scrape job to `prometheus.yml`, pointing at the app's `/metrics` path:

```yaml
scrape_configs:
  - job_name: perevoditarr
    metrics_path: /metrics
    scrape_interval: 30s
    static_configs:
      - targets: ["perevoditarr:8000"]
```

Use the service name and port that match your deployment (the container listens on port
`8000`). Useful signals: `perevoditarr_rail_breaker_state > 0` for provider outages,
`perevoditarr_telemetry_stream_up == 0` for degraded telemetry, and
`rate(perevoditarr_dispatches_total[1h])` for throughput.

## Admin CLI reference

The `perevoditarr` command is the admin CLI. In the container, run it with
`docker exec -it perevoditarr perevoditarr <command>`. Use `perevoditarr --version` to
print the version, and `perevoditarr` with no command to print help.

### `create-user`

Create an admin user.

```bash
perevoditarr create-user --username admin [--password SECRET] [--email you@example.com]
```

- `--username` (required) — the account username.
- `--password` — the password. If omitted, the CLI reads `PEREVODITARR_ADMIN_PASSWORD`,
  and if that is unset, prompts interactively (no echo).
- `--email` — optional email address.

Created users are admins. On success it prints `created user <name> (admin=True)`.

### `run-doctor`

Run the configuration doctor once and print findings.

```bash
perevoditarr run-doctor
```

Prints one `[SEVERITY] CHECK_ID: message` line per finding, then a summary count of
critical/warning/info. Exits with status `2` if any critical finding is present (useful
in health scripts). The doctor is read-only; see the
[doctor reference](doctor-reference.md).

### `resync`

Resync each enabled Bazarr instance's library mirror and wanted state.

```bash
perevoditarr resync [--instance "Main"]
```

- `--instance` — limit the resync to one Bazarr instance by name; omit to resync all
  enabled instances.

Prints `resynced <name>` per instance and a final `resync complete: N instance(s)`.

### `export-config`

Export presets, translation profiles, and assignments as indented JSON (the same
`PolicyExport` document as `GET /api/v1/policy/export`).

```bash
perevoditarr export-config [--out /config/policies.json]
```

- `--out` — write to a file (prints `wrote <path>`); omit to print to stdout.

See the [preset sharing guide](preset-sharing.md).

### `export-openapi`

Dump the OpenAPI 3.1 schema as JSON for code generation.

```bash
perevoditarr export-openapi [--out /config/openapi.json]
```

- `--out` — write to a file; omit to print to stdout.

See the [API guide](api-guide.md).

## Background loops

Perevoditarr runs several scheduled loops whose intervals are configured through
`PEREVODITARR_*` environment variables (see the
[environment reference](install.md#environment-reference)). Each interval is in seconds,
and setting an interval to `0` disables that loop. Notable ones: `SYNC_INTERVAL_SECONDS`
(library mirror), `RECONCILE_INTERVAL_SECONDS` and `VERIFY_INTERVAL_SECONDS`
(correctness plane), `DISPATCH_INTERVAL_SECONDS` (dispatcher), `DOCTOR_INTERVAL_SECONDS`
(scheduled doctor), `TELEMETRY_POLL_INTERVAL_SECONDS` (telemetry polling fallback),
`STATS_ROLLUP_INTERVAL_SECONDS`, and `BUDGET_RECONCILE_INTERVAL_SECONDS`.
