"""Evidence collectors against the simulators (P2-T4).

Each collector is exercised independently through an ASGI-transport client,
following the contract-test conventions (P1-T8 simulators as the upstream).
"""

from collections.abc import AsyncIterator

import pytest

from perevoditarr.modules.integrations.bazarr import BazarrClient
from perevoditarr.modules.integrations.lingarr import LingarrClient
from perevoditarr.modules.intents.collectors import (
    BazarrHistoryCollector,
    BazarrMetadataCollector,
    LingarrRequestCollector,
)
from perevoditarr.modules.intents.evidence import (
    history_evidence,
    lingarr_evidence_for_episode,
    subtitle_presence,
)
from tests.simulators.bazarr import SimSubtitle
from tests.simulators.scenario import Scenario, asgi_client


@pytest.fixture
async def scenario() -> AsyncIterator[Scenario]:
    s = Scenario()
    yield s
    await s.aclose()


@pytest.fixture
async def bazarr_api(scenario: Scenario) -> AsyncIterator[BazarrClient]:
    http = asgi_client(scenario.bazarr.app, base_url="http://bazarr.test")
    http.headers["X-API-KEY"] = scenario.bazarr.api_key
    yield BazarrClient(http)
    await http.aclose()


@pytest.fixture
async def lingarr_api(scenario: Scenario) -> AsyncIterator[LingarrClient]:
    http = asgi_client(scenario.lingarr.app, base_url="http://lingarr.test")
    http.headers["X-Api-Key"] = scenario.lingarr.api_key
    yield LingarrClient(http)
    await http.aclose()


class TestBazarrMetadataCollector:
    async def test_episode_subtitles_batched_by_series(
        self, scenario: Scenario, bazarr_api: BazarrClient
    ) -> None:
        series = scenario.seed_series(title="Alpha Show", episode_count=2)
        target_episode = max(scenario.bazarr.episodes)
        scenario.bazarr.episodes[target_episode].subtitles.append(
            SimSubtitle(code2="da", path="/subs/e2.da.srt")
        )
        collector = BazarrMetadataCollector(bazarr_api)

        collected = await collector.episode_subtitles([series.sonarr_series_id])

        assert set(collected) == set(scenario.bazarr.episodes)
        hit = subtitle_presence(
            collected[target_episode], language="da", forced=False, hi=False
        )
        miss = subtitle_presence(
            collected[target_episode - 1], language="da", forced=False, hi=False
        )
        assert hit.file_backed
        assert not miss.present

    async def test_movie_subtitles_read_only_the_requested_ids(
        self, scenario: Scenario, bazarr_api: BazarrClient
    ) -> None:
        first = scenario.seed_movie(title="Alpha Movie")
        _ = scenario.seed_movie(title="Beta Movie")
        collector = BazarrMetadataCollector(bazarr_api)

        collected = await collector.movie_subtitles([first.radarr_id])

        assert set(collected) == {first.radarr_id}


class TestBazarrHistoryCollector:
    async def test_episode_history_carries_action_6(
        self, scenario: Scenario, bazarr_api: BazarrClient
    ) -> None:
        _ = scenario.seed_series(title="Alpha Show", episode_count=1)
        episode_id = max(scenario.bazarr.episodes)
        scenario.bazarr.episode_history.append(
            {
                "action": 6,
                "timestamp": scenario.clock.now().isoformat(),
                "sonarrSeriesId": 1,
                "sonarrEpisodeId": episode_id,
                "language": {
                    "name": "Danish",
                    "code2": "da",
                    "code3": "dax",
                    "forced": False,
                    "hi": False,
                },
                "subtitles_path": "/subs/e1.da.srt",
                "description": "translated using Lingarr",
                "upgradable": True,
            }
        )
        collector = BazarrHistoryCollector(bazarr_api)

        items = await collector.episode_history(episode_id)
        evidence = history_evidence(items, language="da", forced=False, hi=False)

        assert evidence.translated
        other = await collector.episode_history(episode_id + 99)
        assert other == ()

    async def test_movie_history_empty_without_entries(
        self, scenario: Scenario, bazarr_api: BazarrClient
    ) -> None:
        movie = scenario.seed_movie(title="Alpha Movie")
        collector = BazarrHistoryCollector(bazarr_api)
        assert await collector.movie_history(movie.radarr_id) == ()


class TestLingarrRequestCollector:
    async def test_recent_requests_feed_the_section_6_5_matcher(
        self, scenario: Scenario, lingarr_api: LingarrClient
    ) -> None:
        _ = scenario.lingarr.add_request(
            media_id=11,
            title="Alpha Show",
            source_language="en",
            target_language="da",
            media_type="Episode",
            status="Pending",
        )
        _ = scenario.lingarr.add_request(
            media_id=None,
            title="Other Show",
            source_language="en",
            target_language="da",
            media_type="Episode",
            status="Completed",
        )
        collector = LingarrRequestCollector(lingarr_api)

        records = await collector.recent_requests()

        assert len(records) == 2
        # Two different episodes of the same show resolve to the same record
        # set — the §6.5 coarseness the invariant is built around.
        for _episode in ("s01e01", "s01e02"):
            evidence = lingarr_evidence_for_episode(
                records,
                display_title="Alpha Show",
                source_language="en",
                target_language="da",
            )
            assert [m.request_id for m in evidence.matches] == [1]
            assert evidence.any_active
