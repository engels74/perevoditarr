# ADR-0006 — Dispatch concurrency safety and the scheduling invariant

- Status: Accepted
- Date: 2026-07-02
- Context: P3-T2 (dispatcher), PRD §6.5 (coarse episode identity), §7.2 (bounded
  dispatch window), §6.4 (corruption trap), NFR-3 (single-container topology).

## Decision

The scheduling invariant — **at most one in-flight translation per (Bazarr
instance, series, source→target pair)** for episodes and per (instance, movie,
pair) for movies (§6.5) — is enforced by the dispatcher through two composed
mechanisms, not a database uniqueness constraint:

1. **Per-instance serialization of background passes.** Discovery,
   reconciliation, and dispatch for a given Bazarr instance run under the shared
   `InstanceLockRegistry` (`core/locks.py`). No two passes for the same instance
   interleave inside the process, so the read-then-write "check the in-flight
   pair index, then dispatch and transition to `dispatched`" sequence is atomic
   with respect to other passes for that instance.

2. **The durable in-flight index.** Admission checks the ledger's dispatched
   intents for a matching (instance, series/movie, source→target) pair
   (`ix_intent_series_pair` supports the episode lookup; movies ride the natural
   key). Within a single pass the dispatcher also tracks pairs it has already
   dispatched, so two episodes of one show on the same pair can never both fire
   before the first commits. Because the transition to `dispatched` commits
   before the next candidate is evaluated, the index is always current.

We deliberately do **not** add a partial unique index (e.g.
`UNIQUE (instance, series, src, tgt) WHERE state = 'dispatched'`): partial
indexes are not portably expressible across SQLite and PostgreSQL (NFR-2), and
the single-writer topology makes them unnecessary.

## Why not a DB-level lock or advisory lock

A multi-replica deployment with several processes dispatching for the same
instance concurrently would defeat the in-process lock and could race the
check-then-dispatch window, risking a §6.4 corruption-trap trip. That topology
is explicitly out of scope for v1 (NFR-3: single container). If it is ever
supported, the correct mechanism is a PostgreSQL advisory lock keyed on the
(instance, series/movie, pair) tuple around the admission-and-dispatch critical
section — a localized change to the dispatcher, not a schema change. The
capability-detection slots (§6.6) may also relax the invariant entirely for an
upstream version pair that returns episode-granular identity, at which point the
pair scope widens to episode.

## Consequences

- The corruption trap (§6.4) is unreachable for Perevoditarr-originated traffic
  by construction: only one dispatch per pair can be in flight, and the
  pre-dispatch guard (FR-Q2) additionally re-verifies no matching active Lingarr
  request before firing, covering external actors.
- Crash safety (FR-R4) is preserved: the index is durable ledger state, so after
  a restart re-observation sees exactly the same in-flight pairs.
- The invariant is non-configurable — it is a data-integrity requirement, not a
  tunable rail.
