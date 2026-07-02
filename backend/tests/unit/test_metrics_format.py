"""Prometheus text-format helpers (P4-T3, NFR-6): label escaping + rendering."""

from perevoditarr.core.metrics import (
    escape_label,
    render_metric,
)


def test_metric_without_labels() -> None:
    assert render_metric("perevoditarr_dispatches_total", 42) == (
        "perevoditarr_dispatches_total 42"
    )


def test_metric_with_labels() -> None:
    line = render_metric("perevoditarr_intents", 3, {"state": "eligible"})
    assert line == 'perevoditarr_intents{state="eligible"} 3'


def test_metric_renders_float_compactly() -> None:
    assert render_metric("perevoditarr_sync_duration_seconds", 12.5) == (
        "perevoditarr_sync_duration_seconds 12.5"
    )


def test_escape_label_quotes_backslashes_newlines() -> None:
    assert escape_label('a"b\\c\nd') == 'a\\"b\\\\c\\nd'


def test_metric_escapes_label_values() -> None:
    line = render_metric("m", 1, {"instance": 'we"ird'})
    assert line == 'm{instance="we\\"ird"} 1'
