"""Stats rollup + service + budget reconciliation (P4-T1, FR-U8).

Rollup re-derives the daily counters from the durable `intent_event` audit
trail (restart-safe); the service folds them into the dashboard overview; and
reconciled Lingarr actuals correct both the estimator and the budget rails.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from perevoditarr.core.db import build_alchemy_config, metadata
from perevoditarr.core.security import SecretBox
from perevoditarr.core.settings import AppSettings
from perevoditarr.modules.dispatch.estimation import (
    HEURISTIC_EPISODE_CHARACTERS,
    estimate_intent,
)
from perevoditarr.modules.instances.models import BazarrInstance, LingarrInstance
from perevoditarr.modules.integrations.lingarr.schemas import LingarrStatistics
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.rails.repository import dispatch_characters_since
from perevoditarr.modules.stats.reconciliation import (
    effective_actuals,
    upsert_actuals,
)
from perevoditarr.modules.stats.repository import daily_rows, language_rows
from perevoditarr.modules.stats.rollup import run_stats_rollup
from perevoditarr.modules.stats.service import StatsService
from tests.conftest import TEST_SECRET

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)


@pytest.fixture
async def session(app_settings: AppSettings) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(app_settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db_session:
        yield db_session
    await engine.dispose()


async def _seed_instance(session: AsyncSession, *, name: str = "main") -> UUID:
    instance = BazarrInstance(
        name=name,
        url="http://bazarr.test",
        api_key_encrypted=SecretBox(TEST_SECRET).encrypt_text("k"),
    )
    session.add(instance)
    await session.flush()
    return instance.id


async def _intent(
    session: AsyncSession,
    instance_id: UUID,
    *,
    media_type: str = "episode",
    target_language: str = "da",
    external_media_id: int,
) -> Intent:
    intent = Intent(
        bazarr_instance_id=instance_id,
        media_type=media_type,
        external_media_id=external_media_id,
        sonarr_series_id=external_media_id if media_type == "episode" else None,
        display_title="Show",
        source_language="en",
        target_language=target_language,
        state="converged",
    )
    session.add(intent)
    await session.flush()
    return intent


async def _event(
    session: AsyncSession,
    intent: Intent,
    *,
    to_state: str,
    at: datetime,
    from_state: str | None = None,
    evidence: dict[str, object] | None = None,
) -> None:
    session.add(
        IntentEvent(
            intent_id=intent.id,
            actor="test",
            from_state=from_state,
            to_state=to_state,
            reason=to_state,
            evidence=evidence,
            created_at=at,
        )
    )
    await session.flush()


async def test_rollup_counts_outcomes_durations_and_coverage(
    session: AsyncSession, app_settings: AppSettings
) -> None:
    instance_id = await _seed_instance(session)
    # A converged episode: dispatched at T-10min, converged at T.
    converged = await _intent(session, instance_id, external_media_id=1)
    await _event(
        session, converged, to_state="dispatched", at=NOW - timedelta(minutes=10)
    )
    await _event(session, converged, to_state="converged", at=NOW)
    # A superseded episode + a provider failure.
    superseded = await _intent(session, instance_id, external_media_id=2)
    await _event(session, superseded, to_state="superseded", at=NOW)
    failed = await _intent(
        session, instance_id, external_media_id=3, target_language="de"
    )
    await _event(session, failed, to_state="dispatched", at=NOW - timedelta(minutes=5))
    await _event(
        session,
        failed,
        to_state="failed",
        at=NOW,
        evidence={"kind": "failure", "failure_class": "provider"},
    )
    await session.commit()

    alchemy = build_alchemy_config(app_settings)
    written = await run_stats_rollup(alchemy, days=3, now=NOW)
    assert written == 1  # one (instance, day, episode) bucket

    await session.rollback()  # end any read snapshot; see the rollup's commit
    rows = await daily_rows(
        session, since=NOW.date() - timedelta(days=3), until=NOW.date()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.dispatched == 2
    assert row.converged == 1
    assert row.superseded == 1
    assert row.failed == 1
    assert row.failed_provider == 1
    assert row.converged_characters == HEURISTIC_EPISODE_CHARACTERS
    # 10-minute dispatch->converge latency sampled once.
    assert row.duration_samples == 1
    assert row.duration_seconds_total == 600

    languages = await language_rows(
        session, since=NOW.date() - timedelta(days=3), until=NOW.date()
    )
    assert {(lang.target_language, lang.converged) for lang in languages} == {("da", 1)}


async def test_service_overview_folds_totals_and_failure_rates(
    session: AsyncSession, app_settings: AppSettings
) -> None:
    instance_id = await _seed_instance(session)
    for media_id, klass in ((1, "provider"), (2, "transient"), (3, "provider")):
        failed = await _intent(session, instance_id, external_media_id=media_id)
        await _event(
            session,
            failed,
            to_state="failed",
            at=NOW,
            evidence={"kind": "failure", "failure_class": klass},
        )
    await session.commit()

    alchemy = build_alchemy_config(app_settings)
    _ = await run_stats_rollup(alchemy, days=2, now=NOW)

    await session.rollback()  # see the rollup's commit from the other engine
    overview = await StatsService(session).overview(
        days=7, bazarr_instance_id=None, now=NOW
    )
    assert overview.totals.failed == 3
    provider = next(
        f for f in overview.failure_classes if f.failure_class == "provider"
    )
    assert provider.count == 2
    assert provider.rate == pytest.approx(2 / 3)
    assert overview.since == NOW.date() - timedelta(days=6)
    assert overview.until == NOW.date()


async def test_reconciled_actuals_correct_budget_rails(session: AsyncSession) -> None:
    lingarr = LingarrInstance(name="ling", url="http://lingarr.test")
    session.add(lingarr)
    await session.flush()
    instance_id = await _seed_instance(session)
    instance = await session.get(BazarrInstance, instance_id)
    assert instance is not None
    instance.lingarr_instance_id = lingarr.id
    await session.flush()

    # A dispatched episode within the day counts against the budget.
    intent = await _intent(session, instance_id, external_media_id=1)
    await _event(session, intent, to_state="dispatched", at=NOW)
    await session.commit()

    since = NOW - timedelta(days=1)
    heuristic_total = await dispatch_characters_since(
        session, since, bazarr_instance_id=instance_id
    )
    assert heuristic_total == HEURISTIC_EPISODE_CHARACTERS

    # Reconcile actuals well below the heuristic (25 files, 100 chars each) —
    # a large enough sample to override the heuristic.
    stats = LingarrStatistics(
        total_files_translated=25,
        total_lines_translated=250,
        total_characters_translated=2500,
    )
    _ = await upsert_actuals(session, lingarr_instance_id=lingarr.id, stats=stats)
    actuals = await effective_actuals(session, bazarr_instance_id=instance_id)
    assert actuals is not None and actuals.sample_files == 25

    corrected = estimate_intent("episode", actuals)
    corrected_total = await dispatch_characters_since(
        session,
        since,
        bazarr_instance_id=instance_id,
        characters_per={"episode": corrected.characters, "movie": 0},
    )
    assert corrected_total == corrected.characters
    assert corrected_total < heuristic_total
