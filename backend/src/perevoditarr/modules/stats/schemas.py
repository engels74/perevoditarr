"""Stats API DTOs (P4-T1, FR-U8). camelCase on the wire via ApiStruct."""

from datetime import date, datetime
from uuid import UUID

from perevoditarr.core.schemas import ApiStruct


class StatsTotalsDto(ApiStruct):
    dispatched: int
    converged: int
    superseded: int
    failed: int
    converged_characters: int
    # Mean dispatch->convergence latency across sampled convergences (seconds).
    mean_duration_seconds: float | None
    failed_transient: int
    failed_environmental: int
    failed_provider: int
    failed_poison: int


class ThroughputPointDto(ApiStruct):
    day: date
    dispatched: int
    converged: int
    superseded: int
    failed: int


class FailureClassDto(ApiStruct):
    failure_class: str  # transient | environmental | provider | poison
    count: int
    rate: float  # share of all failures in range (0..1)


class CoveragePointDto(ApiStruct):
    day: date
    converged: int
    cumulative: int


class CoverageSeriesDto(ApiStruct):
    target_language: str
    total: int
    points: list[CoveragePointDto]


class BudgetActualsDto(ApiStruct):
    """Reconciled Lingarr actuals vs. the conservative heuristic (FR-U8)."""

    lingarr_instance_id: UUID
    instance_name: str
    has_actuals: bool
    sample_files: int
    lines_per_file: float
    characters_per_file: float
    total_files: int
    total_characters: int
    captured_at: datetime | None
    heuristic_characters_episode: int
    heuristic_characters_movie: int


class StatsOverviewResponse(ApiStruct):
    generated_at: datetime
    since: date
    until: date
    bazarr_instance_id: UUID | None
    totals: StatsTotalsDto
    throughput: list[ThroughputPointDto]
    failure_classes: list[FailureClassDto]
    coverage: list[CoverageSeriesDto]
    budget: list[BudgetActualsDto]
