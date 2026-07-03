# API guide

Perevoditarr exposes a versioned HTTP API under `/api/v1`. The full surface is
documented by the OpenAPI 3.1 schema the app generates from its route handlers, so the
schema is always in sync with the running version.

## Interactive docs (Scalar UI)

The OpenAPI schema is served at `/schema` with the Scalar UI. Open it in a browser at,
for example, `http://localhost:8000/schema` to browse every endpoint, its request and
response schemas, and try calls interactively. The `/schema` path is excluded from the
auth guard so the docs are reachable before you sign in.

## Code generation

Dump the OpenAPI 3.1 schema as JSON to feed a client generator:

```bash
# Print to stdout
docker exec -it perevoditarr perevoditarr export-openapi

# Write to a file
docker exec -it perevoditarr perevoditarr export-openapi --out /config/openapi.json
```

The exported document is the same schema Scalar renders at `/schema`; point your
generator (openapi-generator, orval, or similar) at it.

## Authentication

Interactive sessions use a JWT cookie (login at `/api/v1/auth/login`; OIDC and
forward-auth are also supported). Programmatic clients use an API key sent as a header,
with the same authorization model as sessions. Before any admin exists, the API exposes
only `/api/v1/setup` (see [installation](install.md)).

## Phase 4 (M3) endpoints

The M3 "Insight & polish" milestone added statistics, per-item timelines, and Lingarr
pass-through actions. All paths below are under `/api/v1`.

### Statistics

- `GET /api/v1/stats/overview` — throughput, durations, and failure-rate rollups derived
  from the audit trail (refreshed by the stats rollup loop).
- `GET /api/v1/stats/budget` — rolling budget actuals reconciled against Lingarr's
  statistics endpoint (estimated versus actual volume/cost).

### Per-item timeline

- `GET /api/v1/intents/{intent_id}/timeline` — a single item's timeline, stitching
  Perevoditarr intent events, Lingarr request states, and Bazarr history into one
  ordered view for explainability.

### Lingarr pass-through actions

- `POST /api/v1/intents/{intent_id}/lingarr/{lingarr_request_id}/{action}` — where
  `action` is one of `cancel`, `retry`, `resume`, or `remove`.

These actions **operate on Lingarr**, not Bazarr. They map 1:1 to Lingarr's own
translation-request endpoints, are user-initiated only (they never run automatically),
never touch Bazarr, and every attempt is audit-logged. This is a deliberate, user-only
write surface; an unknown `action` value is rejected. The UI labels these controls
clearly as acting on Lingarr.

## Related endpoints

Preset and profile sharing uses the policy API (`GET /api/v1/policy/export`,
`POST /api/v1/policy/import`, `POST /api/v1/policy/presets/{preset_id}/fork`,
`POST /api/v1/policy/presets/{preset_id}/activate`); see the
[preset sharing guide](preset-sharing.md). Live UI updates come from the SSE stream at
`/api/v1/events` — the browser never polls for live surfaces.
