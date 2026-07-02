"""Volume/budget estimator (P2-T5): pure domain logic, zero I/O imports.

Per-intent character/line estimates feed the plan preview's budget simulation
(and P3's real budget rail). Sources, best first:

1. Rolling actuals from Lingarr's statistics (lines/characters per translated
   file), once the sample is large enough to mean something — padded with
   headroom because per-file variance is high.
2. A runtime-based heuristic. No file access exists (N2), so the constants
   take the *high* end of observed subtitle density — ~14 lines/minute and
   ~45 characters/line against generous runtimes (45 min episodes, 2 h
   movies) — because the PRD risk table demands over- not under-estimation.

Own converged history joins the ladder in Phase 3+ (FR-V3 reconciles actuals
after convergence); the `RollingActuals` input is already the seam for it.
"""

import math
from typing import Literal

import msgspec

from perevoditarr.modules.integrations.lingarr.schemas import LingarrStatistics

type EstimateBasis = Literal["actuals", "heuristic"]
type EstimateMediaType = Literal["episode", "movie"]

# Below this many translated files, per-file averages are noise.
ACTUALS_MIN_SAMPLE = 20
# Conservative padding on actuals-derived averages (estimate high, PRD §14).
ACTUALS_HEADROOM = 1.25

# High-end heuristics: 45 min episode ≈ 630 lines → padded to 800;
# 120 min movie ≈ 1680 lines → padded to 1800; ~45 chars/line.
HEURISTIC_EPISODE_LINES = 800
HEURISTIC_EPISODE_CHARACTERS = 36_000
HEURISTIC_MOVIE_LINES = 1_800
HEURISTIC_MOVIE_CHARACTERS = 81_000


class VolumeEstimate(msgspec.Struct, kw_only=True, frozen=True):
    lines: int
    characters: int
    # Surfaced to the UI so estimates are labeled by provenance (FR-U3).
    basis: EstimateBasis


class RollingActuals(msgspec.Struct, kw_only=True, frozen=True):
    sample_files: int
    lines_per_file: float
    characters_per_file: float


def actuals_from_statistics(stats: LingarrStatistics) -> RollingActuals | None:
    if stats.total_files_translated <= 0:
        return None
    return RollingActuals(
        sample_files=stats.total_files_translated,
        lines_per_file=stats.total_lines_translated / stats.total_files_translated,
        characters_per_file=(
            stats.total_characters_translated / stats.total_files_translated
        ),
    )


def estimate_intent(
    media_type: EstimateMediaType, actuals: RollingActuals | None
) -> VolumeEstimate:
    if actuals is not None and actuals.sample_files >= ACTUALS_MIN_SAMPLE:
        return VolumeEstimate(
            lines=math.ceil(actuals.lines_per_file * ACTUALS_HEADROOM),
            characters=math.ceil(actuals.characters_per_file * ACTUALS_HEADROOM),
            basis="actuals",
        )
    if media_type == "episode":
        return VolumeEstimate(
            lines=HEURISTIC_EPISODE_LINES,
            characters=HEURISTIC_EPISODE_CHARACTERS,
            basis="heuristic",
        )
    return VolumeEstimate(
        lines=HEURISTIC_MOVIE_LINES,
        characters=HEURISTIC_MOVIE_CHARACTERS,
        basis="heuristic",
    )
