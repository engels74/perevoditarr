"""High-fidelity Bazarr & Lingarr API simulators (P1-T8).

These model the researched seam semantics (PRD §6) and underpin the contract,
crash-safety, and corruption-trap suites of later phases. Update them whenever
the pinned upstream versions move; the contract tests are the tripwire.
"""

from tests.simulators.bazarr import BazarrSimulator
from tests.simulators.lingarr import LingarrSimulator
from tests.simulators.scenario import Scenario, SimClock

__all__ = ["BazarrSimulator", "LingarrSimulator", "Scenario", "SimClock"]
