# ADR-0007 — Watch-aware priority integrations (Tautulli / Plex / Jellyfin)

- Status: Accepted
- Date: 2026-07-03
- Context: P5-T1 (watch integrations), PRD FR-X2 / FR-Q5, §9.9 (integrations),
  §11 (`watch_source` + watch-score cache), the priority scorer (P2-T5), and
  the two-plane separation (§7.3).

## Decision

Watch-history integrations feed the **priority scorer only** — never the intent
state machine. A watched/watchlisted title scores higher, so its translations
run sooner under the same rails; nothing about convergence, dispatch admission,
or the scheduling invariant depends on watch data. This keeps watch data firmly
in the "soft signal" tier: its absence, staleness, or inaccuracy can only change
backlog *ordering*, never correctness (mirrors the telemetry-plane rule of §7.3).

### Clients: lean async httpx, not the vendor SDKs

Each source (Tautulli, Plex, Jellyfin) gets its own read-only async httpx client
under `modules/integrations/{tautulli,plex,jellyfin}/`, matching the existing
Bazarr/Lingarr client pattern exactly (one pooled `AsyncClient` per system on the
shared registry, `retries=0`, boundary decode into msgspec structs with
`forbid_unknown_fields=False`). We deliberately do **not** vendor
`python-plexapi` / `jellyfin-apiclient-python`: both are synchronous (blocking
I/O in `async def` is banned), ship their own connection/session handling and
retry behavior we cannot control, and pull large dependency trees for a feature
that only needs a handful of read endpoints. Direct REST keeps every outbound
call on one uniform, retry-free transport.

Consumed surfaces (read-only, all optional and independent):

- **Tautulli** — `GET /api/v2?cmd=get_history` (recent + play-count aggregation)
  and `cmd=get_server_info` (probe). Auth: `apikey` query param.
- **Plex** — `GET /status/sessions/history/all` (server watch history) and
  `GET {DISCOVER}/library/sections/watchlist/all` on `discover.provider.plex.tv`
  (account watchlist, best-effort — skipped if the token is server-scoped).
  Probe: `GET /`. Auth: `X-Plex-Token`.
- **Jellyfin** — `GET /Users` then `GET /Items` filtered `IsPlayed` (playback
  data, per-item play counts aggregated to the show/movie). Probe:
  `GET /System/Info`. Auth: `Authorization: MediaBrowser Token="…"`.

### Normalization and the score cache

Clients return a common `WatchActivity` shape normalized to §6.5 granularity
(show title for episodes; movie title + year). A background refresh loop
aggregates activity across all enabled sources into a per-title `WatchSignal`
(`watched_recently` / `watched_frequently` / `watchlisted`) and upserts it into
the durable `watch_score` cache keyed on `(media_type, title_key, year)`.
Discovery loads that cache once per pass into an in-memory index and looks up
each candidate by normalized title. Reads apply a hard TTL
(`WATCH_SCORE_TTL_SECONDS`) so a failing/removed source ages out instead of
biasing scores forever — the "cache with TTL" of §11.

Title-based matching is inherently fuzzy (the mirror carries Sonarr/Radarr IDs,
watch sources carry their own IDs/titles), but it is acceptable precisely
because the signal is soft. Movie matches require a year match when both sides
carry one; shows match on normalized title alone.

### Scorer wiring

`PriorityWeights` gains three cascading bonuses (`watch_recent_bonus`,
`watch_frequent_bonus`, `watchlist_bonus`). `ScoreFacts` gains an optional
`watch: WatchSignal | None`; when present, `score_intent` adds a `watch`
component to the breakdown and discovery records a `WatchBoosted` trace step
(e.g. "+15 priority: watched recently (Tautulli)") so the boost is fully
explainable in plan preview (FR-V1). When no source is configured the field is
`None`, the component is absent, and scoring is byte-identical to pre-P5.

## Consequences

- Watch integrations are 100% optional: zero configured sources ⇒ zero behavior
  change, no new failure modes on the correctness plane.
- Fuzzy title matching can occasionally miss or mis-attribute a boost; this only
  reorders the backlog and is surfaced in the trace, so it is auditable.
- No phone-home (NFR-9): all traffic is to user-configured source URLs only.
- Credentials are Fernet-encrypted at rest and masked on read (FR-A5), reusing
  the instance-credential `SecretBox`.
