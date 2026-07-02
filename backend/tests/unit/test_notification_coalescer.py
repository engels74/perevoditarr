"""Notification coalescer + event mapping unit tests (P3-T5)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from perevoditarr.modules.notifications.coalescer import NotificationCoalescer
from perevoditarr.modules.notifications.events import NotificationMessage

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def test_first_send_allowed_then_suppressed_within_window() -> None:
    coalescer = NotificationCoalescer()
    route = uuid4()
    assert coalescer.should_send(route, "breaker_tripped", now=NOW, window_seconds=300)
    assert not coalescer.should_send(
        route, "breaker_tripped", now=NOW + timedelta(seconds=299), window_seconds=300
    )


def test_send_allowed_again_after_window() -> None:
    coalescer = NotificationCoalescer()
    route = uuid4()
    assert coalescer.should_send(route, "cap_reached", now=NOW, window_seconds=300)
    assert coalescer.should_send(
        route, "cap_reached", now=NOW + timedelta(seconds=301), window_seconds=300
    )


def test_different_events_and_routes_are_independent() -> None:
    coalescer = NotificationCoalescer()
    route_a, route_b = uuid4(), uuid4()
    assert coalescer.should_send(route_a, "cap_reached", now=NOW, window_seconds=300)
    # Same route, different event — not suppressed.
    assert coalescer.should_send(
        route_a, "breaker_tripped", now=NOW, window_seconds=300
    )
    # Different route, same event — not suppressed.
    assert coalescer.should_send(route_b, "cap_reached", now=NOW, window_seconds=300)


def test_notify_type_mapping() -> None:
    assert (
        NotificationMessage(event="breaker_tripped", title="t", body="b").notify_type
        == "failure"
    )
    assert (
        NotificationMessage(event="breaker_closed", title="t", body="b").notify_type
        == "success"
    )
    assert (
        NotificationMessage(event="daily_digest", title="t", body="b").notify_type
        == "info"
    )
