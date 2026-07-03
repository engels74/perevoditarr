"""Bootstrap token (Layer 1) unit tests: format, TTL, constant-time validate."""

import re

from perevoditarr.core.bootstrap import (
    DEFAULT_TTL_MINUTES,
    TOKEN_LENGTH,
    BootstrapTokenManager,
    InvalidBootstrapTokenError,
    generate_bootstrap_token,
)

_TOKEN_RE = re.compile(r"^[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}$")


class _FakeClock:
    """Manually-advanced monotonic clock for deterministic TTL tests."""

    def __init__(self) -> None:
        self.now: float = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_generated_token_has_expected_format() -> None:
    for _ in range(50):
        token = generate_bootstrap_token()
        assert len(token) == TOKEN_LENGTH == 14
        assert _TOKEN_RE.fullmatch(token) is not None


def test_generated_tokens_are_unique() -> None:
    tokens = {generate_bootstrap_token() for _ in range(200)}
    # 36^12 space: collisions in 200 draws are astronomically unlikely.
    assert len(tokens) == 200


def test_create_returns_and_activates_token() -> None:
    manager = BootstrapTokenManager()
    token = manager.create()
    assert manager.current_token() == token
    assert not manager.is_expired()
    assert manager.validate(token) is True


def test_create_replaces_previous_token() -> None:
    manager = BootstrapTokenManager()
    first = manager.create()
    second = manager.create()
    assert first != second
    assert manager.validate(first) is False
    assert manager.validate(second) is True


def test_validate_is_non_consuming() -> None:
    manager = BootstrapTokenManager()
    token = manager.create()
    assert manager.validate(token) is True
    assert manager.validate(token) is True
    assert manager.current_token() == token


def test_validate_rejects_wrong_token() -> None:
    manager = BootstrapTokenManager()
    _ = manager.create()
    # Same length as a real token, wrong value.
    assert manager.validate("aaaa-bbbb-cccc") is False


def test_validate_rejects_wrong_length() -> None:
    manager = BootstrapTokenManager()
    token = manager.create()
    assert manager.validate(token[:-1]) is False
    assert manager.validate(token + "x") is False


def test_validate_rejects_when_no_active_token() -> None:
    manager = BootstrapTokenManager()
    assert manager.validate("aaaa-bbbb-cccc") is False


def test_non_ascii_candidate_is_rejected_safely() -> None:
    manager = BootstrapTokenManager()
    _ = manager.create()
    # 14 characters but multibyte: must return False, never raise.
    assert manager.validate("aaaa-bbbb-ccc\u00e9") is False


def test_token_expires_after_ttl() -> None:
    clock = _FakeClock()
    manager = BootstrapTokenManager(clock=clock)
    token = manager.create(ttl_minutes=15)
    clock.advance(15 * 60 - 1)
    assert manager.validate(token) is True
    clock.advance(2)  # now past the 15-minute window
    assert manager.is_expired() is True
    assert manager.current_token() is None
    assert manager.validate(token) is False


def test_custom_ttl_is_honoured() -> None:
    clock = _FakeClock()
    manager = BootstrapTokenManager(clock=clock)
    token = manager.create(ttl_minutes=1)
    clock.advance(59)
    assert manager.validate(token) is True
    clock.advance(2)
    assert manager.validate(token) is False


def test_consume_is_single_use() -> None:
    manager = BootstrapTokenManager()
    token = manager.create()
    assert manager.consume(token) is True
    assert manager.consume(token) is False
    assert manager.validate(token) is False
    assert manager.current_token() is None


def test_consume_wrong_token_keeps_active() -> None:
    manager = BootstrapTokenManager()
    token = manager.create()
    assert manager.consume("aaaa-bbbb-cccc") is False
    assert manager.validate(token) is True


def test_clear_drops_active_token() -> None:
    manager = BootstrapTokenManager()
    token = manager.create()
    manager.clear()
    assert manager.current_token() is None
    assert manager.validate(token) is False


def test_default_ttl_constant() -> None:
    assert DEFAULT_TTL_MINUTES == 15


def test_invalid_bootstrap_token_error_shape() -> None:
    error = InvalidBootstrapTokenError("nope")
    assert error.status_code == 403
    assert error.code == "invalid-bootstrap-token"
