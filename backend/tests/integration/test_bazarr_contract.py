"""Bazarr client contract tests against the simulator (P1-T3 / P1-T8)."""

from collections.abc import AsyncIterator

import pytest

from perevoditarr.core.errors import UnsupportedVersionError, UpstreamError
from perevoditarr.modules.integrations.bazarr.capabilities import detect_capabilities
from perevoditarr.modules.integrations.bazarr.client import (
    BazarrClient,
    ensure_supported_version,
    parse_version,
)
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


class TestVersionGate:
    def test_parse_version_variants(self) -> None:
        assert parse_version("1.5.6") == (1, 5, 6)
        assert parse_version("v1.5.6-beta.4") == (1, 5, 6)
        assert parse_version("1.5.6 by packager") == (1, 5, 6)

    def test_minimum_enforced(self) -> None:
        assert ensure_supported_version("1.5.6") == (1, 5, 6)
        assert ensure_supported_version("1.6.0") == (1, 6, 0)
        with pytest.raises(UnsupportedVersionError):
            _ = ensure_supported_version("1.5.5")
        with pytest.raises(UnsupportedVersionError):
            _ = ensure_supported_version("1.4.9")

    def test_capability_slots_default_false(self) -> None:
        probe = detect_capabilities("1.5.6")
        assert probe.translate_returns_job_id is False
        assert probe.lingarr_receives_episode_id is False


class TestSystemEndpoints:
    async def test_status_and_version(self, bazarr_api: BazarrClient) -> None:
        status = await bazarr_api.system_status()
        assert status.bazarr_version == "1.5.6"

    async def test_settings_carry_lingarr_discovery_data(
        self, bazarr_api: BazarrClient
    ) -> None:
        settings = await bazarr_api.system_settings()
        assert settings.general is not None
        assert settings.general.concurrent_jobs == 4
        assert settings.general.upgrade_manual is True
        assert settings.translator is not None
        assert settings.translator.translator_type == "lingarr"
        assert settings.translator.lingarr_url == "http://lingarr.test"
        assert settings.translator.lingarr_token == "lingarr-key"

    async def test_languages_profiles(self, bazarr_api: BazarrClient) -> None:
        profiles = await bazarr_api.languages_profiles()
        assert len(profiles) == 1
        assert profiles[0].profile_id == 1
        languages = [item.language for item in profiles[0].items]
        assert languages == ["en", "da"]

    async def test_wrong_api_key_rejected(self, scenario: Scenario) -> None:
        http = asgi_client(scenario.bazarr.app, base_url="http://bazarr.test")
        http.headers["X-API-KEY"] = "wrong"
        try:
            with pytest.raises(UpstreamError):
                _ = await BazarrClient(http).system_status()
        finally:
            await http.aclose()


class TestLibraryEndpoints:
    async def test_series_episodes_movies_roundtrip(
        self, scenario: Scenario, bazarr_api: BazarrClient
    ) -> None:
        _ = scenario.seed_series(title="Show A", episode_count=2)
        _ = scenario.seed_movie(title="Film B")

        series_page = await bazarr_api.series()
        assert series_page.total == 1
        assert series_page.data[0].title == "Show A"
        assert series_page.data[0].episode_missing_count == 2

        episodes = await bazarr_api.episodes(
            series_ids=[series_page.data[0].sonarr_series_id]
        )
        assert len(episodes) == 2
        assert episodes[0].subtitles[0].code2 == "en"
        assert episodes[0].subtitles[0].path is not None
        assert episodes[0].missing_subtitles[0].code2 == "da"

        movies = await bazarr_api.movies()
        assert movies.total == 1
        assert movies.data[0].title == "Film B"

    async def test_movies_radarr_id_filter(
        self, scenario: Scenario, bazarr_api: BazarrClient
    ) -> None:
        first = scenario.seed_movie(title="Film One")
        _ = scenario.seed_movie(title="Film Two")

        filtered = await bazarr_api.movies(radarr_ids=[first.radarr_id])
        assert [movie.title for movie in filtered.data] == ["Film One"]

        # None means "no filter" — everything comes back.
        unfiltered = await bazarr_api.movies(radarr_ids=None)
        assert unfiltered.total == 2

        # An empty filter means "nothing", never "everything" (httpx would
        # drop the empty param, silently widening the read).
        empty = await bazarr_api.movies(radarr_ids=[])
        assert empty.data == []
        assert empty.total == 0

    async def test_wanted_pages(
        self, scenario: Scenario, bazarr_api: BazarrClient
    ) -> None:
        _ = scenario.seed_series(episode_count=3)
        _ = scenario.seed_movie()

        wanted = await bazarr_api.wanted_episodes(start=0, length=2)
        assert wanted.total == 3
        assert len(wanted.data) == 2
        assert wanted.data[0].missing_subtitles[0].code2 == "da"

        wanted_movies = await bazarr_api.wanted_movies()
        assert wanted_movies.total == 1
        assert wanted_movies.data[0].radarr_id == 1


class TestTranslateDispatch:
    async def test_translate_is_async_204_and_returns_no_job_id(
        self, scenario: Scenario, bazarr_api: BazarrClient
    ) -> None:
        _ = scenario.seed_series(episode_count=1)
        episode = scenario.bazarr.episodes[1]
        source_path = episode.subtitles[0].path
        assert source_path is not None

        # §6.2: 204, nothing else — correlating to a job is only possible
        # fuzzily afterwards.
        await bazarr_api.translate(
            language="da",
            subtitle_path=source_path,
            media_type="episode",
            media_id=episode.sonarr_episode_id,
        )
        jobs = await bazarr_api.jobs(status="pending")
        assert len(jobs) == 1
        assert "Translating from EN to DA" in (jobs[0].job_name or "")

    async def test_translate_unknown_episode_is_404(
        self, bazarr_api: BazarrClient
    ) -> None:
        with pytest.raises(UpstreamError):
            await bazarr_api.translate(
                language="da",
                subtitle_path="/nope.srt",
                media_type="episode",
                media_id=999,
            )

    async def test_processing_writes_history_action_6(
        self, scenario: Scenario, bazarr_api: BazarrClient
    ) -> None:
        _ = scenario.seed_series(episode_count=1)
        episode = scenario.bazarr.episodes[1]
        assert episode.subtitles[0].path is not None
        await bazarr_api.translate(
            language="da",
            subtitle_path=episode.subtitles[0].path,
            media_type="episode",
            media_id=episode.sonarr_episode_id,
        )
        processed = await scenario.process_jobs()
        assert processed == 1

        history = await bazarr_api.episodes_history()
        assert history.total == 1
        entry = history.data[0]
        assert entry.action == 6
        assert entry.sonarr_episode_id == episode.sonarr_episode_id
        # the subtitle now exists in metadata (authoritative evidence, §6.8)
        episodes = await bazarr_api.episodes(series_ids=[episode.sonarr_series_id])
        assert any(s.code2 == "da" for s in episodes[0].subtitles)
        assert not episodes[0].missing_subtitles

    async def test_failed_and_completed_queues_cap_at_10(
        self, scenario: Scenario, bazarr_api: BazarrClient
    ) -> None:
        _ = scenario.seed_series(episode_count=12, missing_languages=("da",))
        for episode in list(scenario.bazarr.episodes.values()):
            path = episode.subtitles[0].path
            assert path is not None
            await bazarr_api.translate(
                language="da",
                subtitle_path=path,
                media_type="episode",
                media_id=episode.sonarr_episode_id,
            )
        _ = await scenario.process_jobs()
        completed = await bazarr_api.jobs(status="completed")
        # §6.2: completed/failed are capped in-memory deques of 10.
        assert len(completed) == 10


class TestJobsBackpressure:
    async def test_pending_depth_readable(
        self, scenario: Scenario, bazarr_api: BazarrClient
    ) -> None:
        _ = scenario.seed_series(episode_count=3)
        for episode in list(scenario.bazarr.episodes.values()):
            path = episode.subtitles[0].path
            assert path is not None
            await bazarr_api.translate(
                language="da",
                subtitle_path=path,
                media_type="episode",
                media_id=episode.sonarr_episode_id,
            )
        pending = await bazarr_api.jobs(status="pending")
        assert len(pending) == 3
        await bazarr_api.delete_job(pending[0].job_id)
        assert len(await bazarr_api.jobs(status="pending")) == 2
