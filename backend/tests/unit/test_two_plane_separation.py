"""Two-plane separation enforcement (P3-T4, §7.3).

The correctness plane (the intent state machine and everything that drives it
from durable evidence) must never import the telemetry plane — telemetry is
ephemeral/fuzzy and may only nudge re-observation, never drive a transition.
This test is the structural guard: it scans the correctness-plane modules'
source and fails if any reaches into `perevoditarr.modules.telemetry`."""

from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "perevoditarr"

# Modules that observe durable evidence and mutate intent state.
_CORRECTNESS_PLANE = (
    "modules/intents/state_machine.py",
    "modules/intents/evidence.py",
    "modules/intents/failure.py",
    "modules/intents/service.py",
    "modules/intents/reconciler.py",
    "modules/intents/discovery.py",
    "modules/intents/discovery_rules.py",
    "modules/intents/collectors.py",
    "modules/dispatch/dispatcher.py",
    "modules/dispatch/verification.py",
    "modules/dispatch/planning.py",
    "modules/rails/evaluation.py",
    "modules/rails/service.py",
)


def test_correctness_plane_never_imports_telemetry() -> None:
    offenders = [
        rel
        for rel in _CORRECTNESS_PLANE
        if "modules.telemetry" in (_SRC / rel).read_text(encoding="utf-8")
    ]
    assert offenders == [], offenders


def test_telemetry_never_drives_state_transitions() -> None:
    # The telemetry plane may read instances/clients and publish SSE, but must
    # not import the intent state machine or the transitioning service.
    banned = ("intents.state_machine", "intents.service", "intents.reconciler")
    offenders: list[str] = []
    for path in (_SRC / "modules" / "telemetry").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        offenders.extend(f"{path.name}:{marker}" for marker in banned if marker in text)
    assert offenders == [], offenders
