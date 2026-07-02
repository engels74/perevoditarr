"""Lingarr client contract tests + the §6.4/§6.5 seam semantics (P1-T3/P1-T8)."""

from collections.abc import AsyncIterator

import pytest

from perevoditarr.core.errors import UnsupportedVersionError, UpstreamError
from perevoditarr.modules.integrations.lingarr.client import (
    DOCTOR_SETTING_KEYS,
    LingarrClient,
    ensure_supported_version,
)
from tests.simulators.scenario import Scenario, asgi_client
from tests.support import json_list


@pytest.fixture
async def scenario() -> AsyncIterator[Scenario]:
    s = Scenario()
    yield s
    await s.aclose()


@pytest.fixture
async def lingarr_api(scenario: Scenario) -> AsyncIterator[LingarrClient]:
    http = asgi_client(scenario.lingarr.app, base_url="http://lingarr.test")
    http.headers["X-Api-Key"] = scenario.lingarr.api_key
    yield LingarrClient(http)
    await http.aclose()


class TestVersionGate:
    def test_pin_enforced(self) -> None:
        # PRD open question #2 resolved: minimum Lingarr is 1.2.4.
        assert ensure_supported_version("1.2.4") == (1, 2, 4)
        assert ensure_supported_version("1.3.0") == (1, 3, 0)
        with pytest.raises(UnsupportedVersionError):
            _ = ensure_supported_version("1.2.3")

    async def test_version_endpoint(self, lingarr_api: LingarrClient) -> None:
        info = await lingarr_api.version()
        assert info.current_version == "1.2.4"


class TestSettings:
    async def test_single_setting(self, lingarr_api: LingarrClient) -> None:
        assert await lingarr_api.get_setting("automation_enabled") == "false"
        assert await lingarr_api.get_setting("does_not_exist") is None

    async def test_doctor_setting_bundle(
        self, scenario: Scenario, lingarr_api: LingarrClient
    ) -> None:
        scenario.set_lingarr_setting("automation_enabled", "true")
        settings = await lingarr_api.doctor_settings()
        assert settings["automation_enabled"] == "true"
        assert settings["service_type"] == "libretranslate"
        # every doctor key the simulator knows comes back
        assert set(settings) == set(DOCTOR_SETTING_KEYS) & set(settings)

    async def test_auth_enforced_when_enabled(self, scenario: Scenario) -> None:
        scenario.set_lingarr_setting("auth_enabled", "true")
        http = asgi_client(scenario.lingarr.app, base_url="http://lingarr.test")
        http.headers["X-Api-Key"] = "wrong-key"
        try:
            with pytest.raises(UpstreamError):
                _ = await LingarrClient(http).get_setting("automation_enabled")
        finally:
            await http.aclose()
        # version endpoint stays anonymous
        http2 = asgi_client(scenario.lingarr.app, base_url="http://lingarr.test")
        try:
            info = await LingarrClient(http2).version()
            assert info.current_version == "1.2.4"
        finally:
            await http2.aclose()


class TestTranslationRequests:
    async def test_active_and_paged_and_detail(
        self, scenario: Scenario, lingarr_api: LingarrClient
    ) -> None:
        record = scenario.lingarr.add_request(
            media_id=None,
            title="Show A",
            source_language="en",
            target_language="da",
            media_type="Episode",
            status="InProgress",
        )
        done = scenario.lingarr.add_request(
            media_id=7,
            title="Film B",
            source_language="en",
            target_language="da",
            media_type="Movie",
            status="Completed",
        )

        active = await lingarr_api.active_requests()
        assert len(active) == 1
        assert active[0].media_type == "Episode"
        assert active[0].media_id is None  # §6.5 sentinel

        page = await lingarr_api.requests_page(page_number=1, page_size=1)
        assert page.total_count == 2
        assert len(page.items) == 1

        detail = await lingarr_api.request_detail(done.id)
        assert detail.status == "Completed"
        assert detail.media_id == 7

        with pytest.raises(UpstreamError):
            _ = await lingarr_api.request_detail(9999)

        _ = record  # keep referenced

    async def test_pass_through_actions(
        self, scenario: Scenario, lingarr_api: LingarrClient
    ) -> None:
        record = scenario.lingarr.add_request(
            media_id=None,
            title="Show A",
            source_language="en",
            target_language="da",
            media_type="Episode",
            status="InProgress",
        )
        detail = await lingarr_api.request_detail(record.id)

        await lingarr_api.cancel_request(detail)
        assert scenario.lingarr.requests[record.id].status == "Cancelled"

        await lingarr_api.resume_request(detail)
        assert scenario.lingarr.requests[record.id].status == "Pending"

        await lingarr_api.retry_request(detail)
        assert len(scenario.lingarr.requests) == 2

        await lingarr_api.remove_request(detail)
        assert record.id not in scenario.lingarr.requests

    async def test_statistics_and_schedule(self, lingarr_api: LingarrClient) -> None:
        stats = await lingarr_api.statistics()
        assert stats.total_lines_translated == 0
        jobs = await lingarr_api.schedule_jobs()
        assert jobs and jobs[0]["jobId"] == "automation"


class TestSeamSemantics:
    """The §6.4 corruption trap and §6.5 identity coarseness — the whole point
    of the simulator pair. These tests document what the scheduling invariant
    must forever keep unreachable for Perevoditarr traffic."""

    async def test_duplicate_active_identity_returns_empty_array(
        self, scenario: Scenario
    ) -> None:
        http = asgi_client(scenario.lingarr.app, base_url="http://lingarr.test")
        body = {
            "arrMediaId": 1,
            "title": "Show A",
            "sourceLanguage": "en",
            "targetLanguage": "da",
            "mediaType": "Episode",
            "lines": [{"position": 0, "line": "Hello"}],
        }
        try:
            # first request is answered with translated lines...
            _ = scenario.lingarr.add_request(
                media_id=None,
                title="Show A",
                source_language="en",
                target_language="da",
                media_type="Episode",
                status="InProgress",
            )
            response = await http.post("/api/translate/content", json=body)
            assert response.status_code == 200
            # ...but an active identical identity yields the empty array —
            # a "successful" response with zero translated lines (§6.4).
            assert json_list(response) == []
        finally:
            await http.aclose()

    async def test_two_episodes_of_same_show_trip_the_trap(
        self, scenario: Scenario
    ) -> None:
        """Two same-show episodes to the same target pair are indistinguishable
        at Lingarr granularity (§6.5): if BOTH are in flight, the second gets
        the empty array and Bazarr still saves a corrupt file (§6.4)."""
        _ = scenario.seed_series(title="Show A", episode_count=2)
        bazarr_http = asgi_client(scenario.bazarr.app, base_url="http://bazarr.test")
        bazarr_http.headers["X-API-KEY"] = scenario.bazarr.api_key
        try:
            for episode in list(scenario.bazarr.episodes.values()):
                path = episode.subtitles[0].path
                assert path is not None
                response = await bazarr_http.patch(
                    "/api/subtitles",
                    params={
                        "action": "translate",
                        "language": "da",
                        "path": path,
                        "type": "episode",
                        "id": episode.sonarr_episode_id,
                        "forced": "False",
                        "hi": "False",
                        "original_format": "False",
                    },
                )
                assert response.status_code == 204

            # Freeze the first request as still-active so the second one
            # races it — exactly the §6.5 concurrency scenario.
            lingarr_http = asgi_client(
                scenario.lingarr.app, base_url="http://lingarr.test"
            )
            try:
                job_one = await scenario.bazarr.process_next_job(lingarr_http)
                assert job_one is not None
                first_record = next(iter(scenario.lingarr.requests.values()))
                first_record.status = "InProgress"

                job_two = await scenario.bazarr.process_next_job(lingarr_http)
                assert job_two is not None
            finally:
                await lingarr_http.aclose()

            # Both episodes are now "translated" in Bazarr's eyes (action 6
            # logged twice) but the second file holds untranslated text.
            assert len(scenario.bazarr.episode_history) == 2
            assert len(scenario.bazarr.corrupted_items) == 1
        finally:
            await bazarr_http.aclose()

    async def test_movies_are_exactly_identifiable(self, scenario: Scenario) -> None:
        """Movies map correctly (radarr id + movie title): no collision."""
        _ = scenario.seed_movie(title="Film A")
        _ = scenario.seed_movie(title="Film B")
        bazarr_http = asgi_client(scenario.bazarr.app, base_url="http://bazarr.test")
        bazarr_http.headers["X-API-KEY"] = scenario.bazarr.api_key
        try:
            for movie in list(scenario.bazarr.movies.values()):
                path = movie.subtitles[0].path
                assert path is not None
                response = await bazarr_http.patch(
                    "/api/subtitles",
                    params={
                        "action": "translate",
                        "language": "da",
                        "path": path,
                        "type": "movie",
                        "id": movie.radarr_id,
                        "forced": "False",
                        "hi": "False",
                        "original_format": "False",
                    },
                )
                assert response.status_code == 204
            _ = await scenario.process_jobs()
            assert scenario.bazarr.corrupted_items == []
            assert len(scenario.bazarr.movie_history) == 2
        finally:
            await bazarr_http.aclose()
