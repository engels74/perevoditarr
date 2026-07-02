"""Failure taxonomy unit tests (P3-T3, §7.4): the pure classifier and the
intent-level exponential backoff."""

from perevoditarr.modules.intents.failure import (
    Converged,
    LingarrFailure,
    NeedsAttention,
    Quarantine,
    RetryScheduled,
    StillWaiting,
    SupersededOther,
    classify_dispatched,
    is_environmental_message,
    retry_backoff_seconds,
)


def _classify(**kwargs: object) -> object:
    base: dict[str, object] = {
        "target_present": False,
        "translated_in_window": False,
        "lingarr_failure": None,
        "lease_expired": False,
        "attempts": 1,
        "max_attempts": 4,
    }
    base.update(kwargs)
    return classify_dispatched(
        target_present=bool(base["target_present"]),
        translated_in_window=bool(base["translated_in_window"]),
        lingarr_failure=base["lingarr_failure"],  # pyright: ignore[reportArgumentType]
        lease_expired=bool(base["lease_expired"]),
        attempts=int(base["attempts"]),  # pyright: ignore[reportArgumentType]
        max_attempts=int(base["max_attempts"]),  # pyright: ignore[reportArgumentType]
    )


def test_converged_needs_present_plus_our_translation() -> None:
    assert isinstance(
        _classify(target_present=True, translated_in_window=True), Converged
    )


def test_present_without_our_translation_is_superseded() -> None:
    assert isinstance(
        _classify(target_present=True, translated_in_window=False), SupersededOther
    )


def test_environmental_failure_needs_attention_no_retry() -> None:
    outcome = _classify(
        lingarr_failure=LingarrFailure(status="Failed", environmental=True)
    )
    assert isinstance(outcome, NeedsAttention)
    assert outcome.failure_class == "environmental"


def test_provider_failure_retries_below_ceiling() -> None:
    outcome = _classify(
        lingarr_failure=LingarrFailure(status="Failed"), attempts=1, max_attempts=4
    )
    assert isinstance(outcome, RetryScheduled)
    assert outcome.failure_class == "provider"


def test_provider_failure_quarantines_at_ceiling() -> None:
    outcome = _classify(
        lingarr_failure=LingarrFailure(status="Failed"), attempts=4, max_attempts=4
    )
    assert isinstance(outcome, Quarantine)
    assert outcome.failure_class == "provider"


def test_lease_expiry_without_evidence_is_transient_retry() -> None:
    outcome = _classify(lease_expired=True, attempts=1)
    assert isinstance(outcome, RetryScheduled)
    assert outcome.failure_class == "transient"


def test_lease_expiry_at_ceiling_quarantines_as_poison() -> None:
    outcome = _classify(lease_expired=True, attempts=4, max_attempts=4)
    assert isinstance(outcome, Quarantine)
    assert outcome.failure_class == "poison"


def test_no_evidence_before_lease_is_still_waiting() -> None:
    assert isinstance(_classify(lease_expired=False), StillWaiting)


def test_environmental_message_detection() -> None:
    assert is_environmental_message("Source file not found: /media/x.srt") is True
    assert is_environmental_message("provider returned HTTP 500") is False
    assert is_environmental_message(None) is False


def test_backoff_is_exponential_and_capped() -> None:
    assert retry_backoff_seconds(1, 300, cap_seconds=21600) == 300
    assert retry_backoff_seconds(2, 300, cap_seconds=21600) == 600
    assert retry_backoff_seconds(3, 300, cap_seconds=21600) == 1200
    # Large attempt counts saturate at the cap without overflowing.
    assert retry_backoff_seconds(100, 300, cap_seconds=21600) == 21600
