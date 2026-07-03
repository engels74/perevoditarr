"""In-memory bootstrap token for first-run setup (Layer 1).

On a fresh install Perevoditarr has no admin account. To let the very first
visitor prove they are the operator (and not a random person who found an
exposed URL), the server mints a short, human-typeable token at startup, prints
it *only* to the logs, and requires it to complete ``POST /api/v1/setup``.

Design (mirrors the reference onboarding overview, adapted to this stack):

- **Memory-only.** The token lives on the per-process ``BootstrapTokenManager``
  (held by ``AuthRuntime``); it is never persisted, so a stolen DB file cannot
  resume setup and a restart or a second worker invalidates it.
- **Log-only delivery.** Whoever can read the logs is, by definition, the
  operator. No HTTP surface ever returns the token.
- **Short TTL (15 min).** Bounds the window an exposed token is useful.
- **Constant-time comparison.** ``hmac.compare_digest`` (with an early length
  gate) prevents timing side-channels from leaking the token character by
  character.

The token is validated once, in the request that creates the first admin
(``POST /api/v1/setup``) — a single atomic step, so there is no separate
persisted "setup claim" layer. That request does not durably finish setup;
completion is a later, admin-only step (``POST /api/v1/setup/finish``).
"""

import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from perevoditarr.core.errors import PerevoditarrError

# 3 segments x 4 chars + 2 dashes => "xxxx-xxxx-xxxx".
_CHARSET = "abcdefghijklmnopqrstuvwxyz0123456789"  # 36 unambiguous, easy to type
_SEGMENTS = 3
_SEGMENT_LEN = 4
TOKEN_LENGTH = _SEGMENTS * _SEGMENT_LEN + (_SEGMENTS - 1)  # 14
DEFAULT_TTL_MINUTES = 15


class InvalidBootstrapTokenError(PerevoditarrError):
    """Setup was attempted without a valid, unexpired bootstrap token."""

    status_code: ClassVar[int] = 403
    code: ClassVar[str] = "invalid-bootstrap-token"
    title: ClassVar[str] = "Invalid bootstrap token"


def generate_bootstrap_token() -> str:
    """Return a fresh ``xxxx-xxxx-xxxx`` token from the OS CSPRNG.

    ``secrets.choice`` draws uniformly from the alphabet (it rejects modulo
    bias internally via ``randbelow``), so no manual rejection sampling is
    needed here.
    """
    segments = [
        "".join(secrets.choice(_CHARSET) for _ in range(_SEGMENT_LEN))
        for _ in range(_SEGMENTS)
    ]
    return "-".join(segments)


@dataclass(slots=True)
class _ActiveToken:
    value: str
    expires_at: float


class BootstrapTokenManager:
    """Per-process holder for the current first-run bootstrap token.

    A single instance lives on ``AuthRuntime``; it is never shared across
    processes, which is what binds first-run setup to *this* running worker.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock: Callable[[], float] = clock
        self._active: _ActiveToken | None = None

    def create(self, ttl_minutes: int = DEFAULT_TTL_MINUTES) -> str:
        """Mint a fresh token, replacing any previous one, and return it."""
        token = generate_bootstrap_token()
        self._active = _ActiveToken(
            value=token, expires_at=self._clock() + ttl_minutes * 60
        )
        return token

    def _drop_if_expired(self) -> None:
        if self._active is not None and self._clock() >= self._active.expires_at:
            self._active = None

    def is_expired(self) -> bool:
        """True when there is no token, or the active one has aged out."""
        self._drop_if_expired()
        return self._active is None

    def current_token(self) -> str | None:
        """Return the active token value, or None if absent/expired.

        Reads in-memory state only; used by tests and never exposed over HTTP.
        """
        self._drop_if_expired()
        return self._active.value if self._active is not None else None

    def validate(self, candidate: str) -> bool:
        """Constant-time check that ``candidate`` matches the active token.

        Non-consuming: a valid token stays usable for its full TTL. Returns
        False when there is no active token, it has expired, or the length
        differs (an early gate that bounds work on untrusted input).
        """
        self._drop_if_expired()
        if self._active is None:
            return False
        if len(candidate) != TOKEN_LENGTH:
            return False
        # Compare as bytes so any candidate str can never raise. ``surrogatepass``
        # covers lone surrogates (which plain UTF-8 encoding rejects with
        # UnicodeEncodeError); a value mismatch there is handled safely by
        # compare_digest, so a surrogate candidate returns False, never raises.
        return hmac.compare_digest(
            candidate.encode("utf-8", "surrogatepass"),
            self._active.value.encode("utf-8", "surrogatepass"),
        )

    def consume(self, candidate: str) -> bool:
        """Validate and, on success, clear the token (single-use path).

        Not used by the live setup flow, which keeps the token usable for its
        TTL so a lost attempt can be retried; retained for completeness.
        """
        if self.validate(candidate):
            self._active = None
            return True
        return False

    def clear(self) -> None:
        """Unconditionally drop the active token (called when setup completes)."""
        self._active = None
