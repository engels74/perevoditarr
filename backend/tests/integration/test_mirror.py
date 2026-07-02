"""Mirror sync + browse end-to-end against the simulators (P1-T5)."""

from collections.abc import Iterator

import pytest
from litestar import Litestar
from litestar.testing import TestClient

from tests.conftest import complete_setup, csrf_headers
from tests.integration.test_instances import SimulatorGateway
from tests.simulators.scenario import Scenario


@pytest.fixture
def scenario() -> Scenario:
    s = Scenario()
    _ = s.seed_series(title="Alpha Show", episode_count=4)
    _ = s.seed_series(title="The Beta Show", episode_count=3)
    _ = s.seed_series(title="Gamma", episode_count=2, missing_languages=())
    _ = s.seed_movie(title="First Movie")
    _ = s.seed_movie(title="Second Movie", missing_languages=())
    return s


@pytest.fixture
def client(app: Litestar, scenario: Scenario) -> Iterator[TestClient[Litestar]]:
    app.state["gateway"] = SimulatorGateway(scenario)
    with TestClient(app=app) as test_client:
        complete_setup(test_client)
        yield test_client


@pytest.fixture
def instance_id(client: TestClient[Litestar]) -> str:
    response = client.post(
        "/api/v1/instances/bazarr",
        json={"name": "main", "url": "http://bazarr.test", "apiKey": "bazarr-key"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _sync(
    client: TestClient[Litestar], instance_id: str, *, full: bool = False
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/mirror/sync/{instance_id}?full={'true' if full else 'false'}",
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _sync_wanted(client: TestClient[Litestar], instance_id: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/mirror/sync/{instance_id}/wanted", headers=csrf_headers(client)
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestLibrarySync:
    def test_full_sync_mirrors_library(
        self, client: TestClient[Litestar], instance_id: str
    ) -> None:
        run = _sync(client, instance_id, full=True)
        assert run["status"] == "completed"
        counters = run["counters"]
        assert isinstance(counters, dict)
        assert counters["series"] == 3
        assert counters["episodes"] == 9
        assert counters["movies"] == 2
        assert counters["subtitles"] == 11  # one source subtitle per item

        series = client.get("/api/v1/mirror/series").json()
        assert series["total"] == 3
        titles = [row["title"] for row in series["items"]]
        # sort_title ordering: "Alpha Show", "The Beta Show" (beta), "Gamma"
        assert titles == ["Alpha Show", "The Beta Show", "Gamma"]

    def test_sync_is_idempotent(
        self, client: TestClient[Litestar], instance_id: str
    ) -> None:
        _ = _sync(client, instance_id)
        _ = _sync(client, instance_id)
        series = client.get("/api/v1/mirror/series").json()
        assert series["total"] == 3
        movies = client.get("/api/v1/mirror/movies").json()
        assert movies["total"] == 2

    def test_full_sync_removes_vanished_series(
        self, client: TestClient[Litestar], instance_id: str, scenario: Scenario
    ) -> None:
        _ = _sync(client, instance_id, full=True)
        removed = scenario.bazarr.series.pop(1)
        scenario.bazarr.episodes = {
            k: e
            for k, e in scenario.bazarr.episodes.items()
            if e.sonarr_series_id != removed.sonarr_series_id
        }
        _ = _sync(client, instance_id, full=True)
        series = client.get("/api/v1/mirror/series").json()
        assert series["total"] == 2
        assert all(row["title"] != "Alpha Show" for row in series["items"])

    def test_episode_drilldown_with_subtitles(
        self, client: TestClient[Litestar], instance_id: str
    ) -> None:
        _ = _sync(client, instance_id)
        _ = _sync_wanted(client, instance_id)
        series = client.get("/api/v1/mirror/series?search=alpha").json()
        assert series["total"] == 1
        series_row = series["items"][0]
        episodes = client.get(
            f"/api/v1/mirror/series/{series_row['id']}/episodes"
        ).json()
        assert episodes["total"] == 4
        first = episodes["items"][0]
        assert first["season"] == 1
        assert [s["language"] for s in first["subtitles"]] == ["en"]
        assert [w["language"] for w in first["wanted"]] == ["da"]


class TestWantedSync:
    def test_wanted_rows_and_withdrawal(
        self, client: TestClient[Litestar], instance_id: str, scenario: Scenario
    ) -> None:
        _ = _sync(client, instance_id)
        run = _sync_wanted(client, instance_id)
        counters = run["counters"]
        assert isinstance(counters, dict)
        assert counters["wanted_episodes"] == 7  # 4 + 3 (Gamma has none)
        assert counters["wanted_movies"] == 1

        # Upstream satisfies one wanted item (e.g. an indexer download) —
        # the next pass withdraws it from the mirror.
        episode = scenario.bazarr.episodes[1]
        episode.missing = []
        run2 = _sync_wanted(client, instance_id)
        counters2 = run2["counters"]
        assert isinstance(counters2, dict)
        assert counters2["withdrawn"] == 1

    def test_first_seen_preserved_across_passes(
        self, client: TestClient[Litestar], instance_id: str
    ) -> None:
        _ = _sync(client, instance_id)
        _ = _sync_wanted(client, instance_id)
        _ = _sync_wanted(client, instance_id)
        runs = client.get(f"/api/v1/mirror/sync-runs?instance_id={instance_id}").json()
        wanted_runs = [r for r in runs["items"] if r["kind"] == "wanted"]
        assert len(wanted_runs) == 2
        assert all(r["status"] == "completed" for r in wanted_runs)


class TestBrowseAndDashboard:
    def test_missing_language_filter(
        self, client: TestClient[Litestar], instance_id: str
    ) -> None:
        _ = _sync(client, instance_id)
        _ = _sync_wanted(client, instance_id)
        missing_da = client.get("/api/v1/mirror/series?missing_language=da").json()
        assert missing_da["total"] == 2  # Gamma seeded with no missing languages
        missing_de = client.get("/api/v1/mirror/series?missing_language=de").json()
        assert missing_de["total"] == 0

    def test_coverage_stats(
        self, client: TestClient[Litestar], instance_id: str
    ) -> None:
        _ = _sync(client, instance_id)
        _ = _sync_wanted(client, instance_id)
        coverage = {
            c["language"]: c for c in client.get("/api/v1/mirror/coverage").json()
        }
        assert coverage["en"]["episodesWithSubtitle"] == 9
        assert coverage["en"]["moviesWithSubtitle"] == 2
        assert coverage["da"]["episodesWanted"] == 7
        assert coverage["da"]["moviesWanted"] == 1

    def test_freshness(self, client: TestClient[Litestar], instance_id: str) -> None:
        stale = client.get("/api/v1/mirror/freshness").json()
        assert stale[0]["stale"] is True
        _ = _sync(client, instance_id)
        fresh = client.get("/api/v1/mirror/freshness").json()
        assert fresh[0]["stale"] is False
        assert fresh[0]["lastFullSyncAt"] is not None
