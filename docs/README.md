# Perevoditarr documentation

Perevoditarr is a self-hosted orchestration and observability application that sits
between [Bazarr](https://www.bazarr.media/) (subtitle management) and
[Lingarr](https://github.com/lingarr-translate/lingarr) (subtitle translation). It
automates subtitle translation *through Bazarr's translate API* as a declarative
reconciliation engine, so every translated subtitle stays tracked, upgradeable, and
native to Bazarr's state, while enforcing hard safety rails (dispatch window, volume
caps, budget ceilings, circuit breakers, quarantine) and staying safe-by-default.

These pages assume Bazarr **>= v1.5.6** and Lingarr **>= 1.2.4**; Perevoditarr checks
both versions at instance registration and refuses older instances.

## Pages

- [Installation](install.md) — deploy with Docker Compose for PostgreSQL or SQLite,
  required environment, and the first-run `/setup` flow.
- [Onboarding](onboarding.md) — the Observe -> plan -> activate walkthrough: register
  instances, sync the mirror, preview the dry-run plan, then activate per instance.
- [Preset sharing](preset-sharing.md) — fork, export, and import presets and
  translation profiles via the UI, the policy API, and `perevoditarr export-config`.
- [Doctor reference](doctor-reference.md) — the read-only configuration doctor's
  check catalogue, severities, and the Lingarr-automation conflict detection.
- [API guide](api-guide.md) — the `/api/v1` surface, the Scalar UI at `/schema`,
  `perevoditarr export-openapi` for codegen, and the Phase 4 endpoints.
- [Troubleshooting](troubleshooting.md) — the Lingarr automation conflict explainer,
  telemetry degradation, breaker trips, quarantine, and needs-attention.
- [Operations](operations.md) — the Prometheus metrics endpoint at `/metrics`, a
  sample scrape config, and the admin CLI reference.
