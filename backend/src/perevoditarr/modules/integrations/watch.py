"""Shared watch-integration contract (P5-T1, FR-X2).

The three watch sources — Tautulli, Plex, Jellyfin — each expose their own
read-only client under `integrations/{tautulli,plex,jellyfin}/`, but all
normalize to the common `WatchActivity` shape defined here so the `watch`
feature module never branches per source. Deliberately imports nothing from
sqlalchemy/litestar: this is the plain vocabulary shared by the clients and
their consumers.

Identity is §6.5-coarse on purpose: a show is its title, a movie its title +
year — the same granularity the scheduling invariant and Lingarr's dedup use.
Watch data is a *soft priority signal only* (ADR-0007): it can reorder the
backlog but never drives the intent state machine.
"""

import re
import unicodedata
from typing import Literal, Protocol

import msgspec

type WatchSourceType = Literal["tautulli", "plex", "jellyfin"]
type WatchMediaType = Literal["show", "movie"]

WATCH_SOURCE_TYPES: tuple[WatchSourceType, ...] = ("tautulli", "plex", "jellyfin")

_WHITESPACE = re.compile(r"\s+")
_TRAILING_YEAR = re.compile(r"\s*\((?:19|20)\d{2}\)\s*$")


def normalize_title(title: str) -> str:
    """Collapse a display title to a stable match key.

    casefold + Unicode NFKD + whitespace collapse + trailing "(YYYY)" strip, so
    "The Office (2005)" and "the  office" collapse to the same key. Kept
    deliberately simple — the boost is soft, so a rare miss only reorders the
    backlog (ADR-0007)."""
    folded = unicodedata.normalize("NFKD", title).casefold().strip()
    folded = _TRAILING_YEAR.sub("", folded)
    return _WHITESPACE.sub(" ", folded).strip()


class WatchActivity(msgspec.Struct, kw_only=True, frozen=True):
    """One normalized watch signal for a title, from one source.

    `last_watched_at` is epoch seconds (UTC); watch sources report play times in
    a mix of formats, so clients convert to this single scalar at the boundary.
    """

    media_type: WatchMediaType
    title: str
    # Movie disambiguation; None for shows (matched on title alone, §6.5).
    year: int | None = None
    last_watched_at: int | None = None
    play_count: int = 0
    watchlisted: bool = False


class WatchSignal(msgspec.Struct, kw_only=True, frozen=True):
    """The aggregated, per-title scorer input the watch module derives from raw
    `WatchActivity` across every enabled source. Consumed by the pure priority
    scorer (policy) — no I/O, so it lives in the shared contract to keep policy
    and watch decoupled (ADR-0007)."""

    watched_recently: bool = False
    watched_frequently: bool = False
    watchlisted: bool = False
    # Source names that contributed, for the human-readable trace step.
    sources: tuple[str, ...] = ()


class WatchSourceProbe(msgspec.Struct, kw_only=True, frozen=True):
    """Connectivity + identity for the doctor and the connection-test endpoint."""

    reachable: bool
    identity: str | None = None
    version: str | None = None
    detail: str | None = None


class WatchSourceClient(Protocol):
    """The read-only surface every watch source implements."""

    async def probe(self) -> WatchSourceProbe: ...

    async def fetch_activity(
        self, *, window_days: int, limit: int
    ) -> list[WatchActivity]: ...
