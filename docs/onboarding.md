# Onboarding: Observe -> plan -> activate

Perevoditarr is safe-by-default. On a fresh install the **Observe** preset is active:
it discovers your library, builds a plan, and reports what it *would* do, but dispatches
nothing. You move from observing to translating deliberately, one instance at a time,
after you have reviewed the plan and confirmed the safety rails in force. Nothing writes
to Bazarr until you explicitly activate.

This walkthrough covers the three stages: **Observe** (register and sync), **plan**
(review the dry-run preview), and **activate** (turn on dispatch per instance).

## 1. Observe: register instances and sync the mirror

### Register Bazarr and Lingarr

1. Sign in (see [installation](install.md) for the first-run `/setup` flow).
2. Open **Settings -> Instances** and add a Bazarr instance (URL and API key).
   Perevoditarr checks the version at registration and refuses Bazarr older than
   **v1.5.6** and Lingarr older than **1.2.4**.
3. Perevoditarr auto-discovers the Lingarr instance that Bazarr delegates translation
   to (Bazarr's `translator_type` must be `lingarr` with a Lingarr URL/token set). It
   reads Lingarr's settings as authoritative for planning and for the doctor.

### Run the doctor

Open the **Doctor** panel and run it. The doctor is read-only in v1: it never changes
Bazarr, Lingarr, or Perevoditarr settings. It reports info/warn/critical findings with
an explanation and fix guidance for each. Resolve any **critical** findings before you
activate. The most important one to clear before going live is **FR-DR2** (Lingarr's own
automation is on) — running Lingarr automation alongside Perevoditarr causes double
work, wasted spend, and dedup collisions. See the [doctor reference](doctor-reference.md)
and the [troubleshooting guide](troubleshooting.md) for details.

### Sync the library mirror

Perevoditarr keeps a durable mirror of Bazarr's series, episodes, and movies plus their
subtitle/coverage state. The mirror syncs on a schedule
(`PEREVODITARR_SYNC_INTERVAL_SECONDS`, default hourly), and you can trigger it on demand
from the UI or with the CLI:

```bash
docker exec -it perevoditarr perevoditarr resync
# or limit to one Bazarr instance by name:
docker exec -it perevoditarr perevoditarr resync --instance "Main"
```

Browse the **Library** view once the mirror is populated to confirm coverage looks
right before planning.

## 2. Plan: review the dry-run preview

Open the **Plan** view — the primary Observe-mode surface. It shows "what would happen
next and why": the next batch of candidate translations under the current preset's rails
and caps, each with its decision trace (the rule chain that produced it) and an estimated
volume and budget impact. Estimates come from rolling actuals reconciled against Lingarr
statistics plus runtime heuristics, and are intentionally conservative (estimated high).

While the Observe preset is active, all rails are *simulated* — the plan reflects what
the dispatch window, volume caps, budget ceilings, and scheduling windows would allow,
but still dispatches nothing. Use this stage to:

- Confirm the target languages and source preferences match your intent.
- Sanity-check estimated volume and cost against your budget.
- Adjust profiles, presets, exclusions, and assignments until the plan is what you want.

See the [preset sharing guide](preset-sharing.md) for tuning and sharing presets and
translation profiles.

## 3. Activate: turn on dispatch per instance

Activation is explicit and per instance (and per profile), never global-by-accident.
From the dashboard or queue, use the **activation flow** to transition an instance from
**Observe** to **Active**. Before it takes effect, Perevoditarr shows a confirmation
that summarizes the rails that will be in force, for example:

- **Dispatch window** — at most K intents in flight per Bazarr instance, always leaving
  headroom relative to that instance's `concurrent_jobs`, and backpressure-aware
  (it holds top-up when Bazarr's pending queue is deep).
- **Scheduling invariant** — at most one in-flight translation per (instance, series,
  source->target pair) for episodes and per (instance, movie, source->target pair) for
  movies. This is non-configurable and makes the duplicate-translation corruption trap
  unreachable for Perevoditarr's own traffic.
- **Volume caps** — per hour/day/week, per instance and global.
- **Budget ceilings** — estimated characters/lines per period versus your limit.
- **Scheduling windows** — cron-like active windows.
- **Circuit breakers** — per instance-pair; trip on repeated provider/Lingarr failure,
  half-open probe for recovery, notify on trip and close.

Confirm the summary to activate. Every rail that is currently limiting shows a visible
explanation in the UI (for example, "Paused: daily cap reached (200/200), resets in
6 h 12 m"), so idleness is always explained.

You can keep some instances or profiles in dry-run while others are active, and a global
or per-instance pause (persisted across restarts) is always one click away. To back out,
pause the instance or switch it back to the Observe preset — dispatch stops immediately
and no in-flight intents are lost.
