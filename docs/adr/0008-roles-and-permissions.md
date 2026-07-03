# ADR-0008 — Roles: admin vs. viewer (and why not per-instance permissions)

- Status: Accepted
- Date: 2026-07-03
- Context: P5-T2 (extended auth & roles), PRD FR-A6, and PRD open question #3
  ("roles granularity beyond admin/viewer — per-instance permissions? — deferred
  to M4 scoping"). This ADR resolves open question #3.

## Decision

v1 ships exactly **two global roles**:

- **admin** — full read/write across every module and setting.
- **viewer** — read-only observer: may read every `/api/v1` surface and manage
  its own session (logout/refresh) but may perform no state mutation anywhere.

**Per-instance / per-module permissions are explicitly out of scope for v1.**

### Model

`user.role` is a first-class column (`admin` | `viewer`, default `admin`). The
prior boolean `is_admin` column is dropped and replaced by a read-only Python
property (`role == "admin"`) so existing call sites and the `UserRead` DTO keep
working, but there is a single source of truth.

### Enforcement

Enforcement is method-based, applied **once** as a guard on the `/api/v1`
router rather than sprinkled across ~40 handlers (which would rot):

1. Unauthenticated handlers (`exclude_from_auth`: setup, login, OIDC callback,
   webhook ingestion) are untouched — no `scope["user"]` is set, so the guard
   is a no-op for them.
2. For an authenticated **viewer**: `GET`/`HEAD`/`OPTIONS` always pass; any
   other method is denied `403` **unless** the handler opts in via
   `opt={"viewer_write": True}`.
3. The small viewer-write allowlist covers only self-service session endpoints
   (logout, refresh) and read-style POSTs (doctor run, plan preview, connection
   tests) that mutate nothing in the domain.
4. Admin-only endpoints keep their explicit `require_admin` guard (now
   role-based) as defense in depth.

Admins provision viewers through the user-management API
(`/api/v1/auth/users`, admin-only) or the CLI (`create-user --role viewer`).

## Why not per-instance permissions in v1

The primary persona is a single self-hosting operator (PRD §5); multi-tenant,
per-instance delegation has no concrete demand yet and would leak scoping into
every module's authorization checks. A global admin/viewer split delivers the
"read-only observer" use case (share a dashboard without risk) at a fraction of
the surface area. If per-instance permissions are ever needed, `user.role`
generalizes to a role/permission join without disturbing the method-based guard
seam.

## Consequences

- Viewers get a safe, complete read-only product; the UI additionally hides
  write controls when `session.user.isAdmin` is false (defense in depth, not the
  authority — the API guard is authoritative).
- Adding a new write endpoint is safe-by-default: it is denied to viewers unless
  explicitly opted in.
- The `role` column is dialect-portable (plain string, NFR-2); the migration
  backfills `admin` from the old `is_admin=true` rows.
