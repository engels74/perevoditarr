# Preset and profile sharing

Perevoditarr's automation behavior resolves through a strict, most-specific-wins
cascade:

```
Global defaults -> Active preset -> Translation profile -> Per-item override
```

**Presets** are shippable, forkable bundles of defaults that constitute the onboarding
story (Observe, Conservative, Balanced, Aggressive). **Translation profiles** bundle the
*what* and *how* of translation (target languages, ordered source preferences, HI/forced
rules, grace periods, skip conditions) for the media they are assigned to. Both are
duplicatable, editable, and exportable/importable as JSON for community sharing.

## Fork a preset

Forking duplicates a preset so you can edit the copy without touching the original
(including the shipped presets). In the UI, open **Settings -> Policy**, pick a preset,
and choose fork/duplicate. Over the API:

```
POST /api/v1/policy/presets/{preset_id}/fork
{ "name": "My Balanced" }
```

Activate a preset (only one is active at a time):

```
POST /api/v1/policy/presets/{preset_id}/activate
```

## Export and import over the policy API

The policy export/import surface (FR-U6) round-trips presets, profiles, assignments,
exclusions, and overrides as a single schema-versioned JSON document, validated on
import.

Export:

```
GET /api/v1/policy/export
```

Import:

```
POST /api/v1/policy/import
```

The import request body is the previously exported document (wrapped in the import
request schema). Because the payload is schema-versioned and validated, a document
exported from one instance can be imported into another for sharing or migration. See
the [API guide](api-guide.md) for the authoritative request/response shapes in the
Scalar UI at `/schema`.

## Export from the command line

The admin CLI exports the same policy data (presets, profiles, and assignments) as
indented JSON, without needing an authenticated API session:

```bash
# Print to stdout
docker exec -it perevoditarr perevoditarr export-config

# Write to a file inside the container
docker exec -it perevoditarr perevoditarr export-config --out /config/policies.json
```

`export-config` produces the same `PolicyExport` document that `GET /api/v1/policy/export`
returns, so you can export with the CLI and import the file through
`POST /api/v1/policy/import` (or share it with another operator to import into their
instance).

## Sharing workflow

1. Tune a preset (fork a shipped one first so you keep the defaults) and its assigned
   translation profiles until the [plan preview](onboarding.md) reflects your intent.
2. Export with `perevoditarr export-config` or `GET /api/v1/policy/export`.
3. Share the JSON. The recipient imports it through `POST /api/v1/policy/import`.
4. On the recipient's instance, review the doctor and the plan preview before
   activating — target languages are validated against each Bazarr instance's language
   profiles and each pair against Lingarr's configured languages, so a shared profile
   may surface findings that need local adjustment.
