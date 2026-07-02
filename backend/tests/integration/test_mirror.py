"""Mirror sync + browse end-to-end against the simulators (P1-T5)."""

from collections.abc import Iterator

import pytest
from litestar import Litestar
from litestar.testing import TestClient

from tests.conftest import complete_setup, csrf_headers
from tests.integration.test_instances import SimulatorGateway
from tests.simulators.scenario import Scenario
from tests.support import as_list, as_obj, json_list, json_obj


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
    return str(json_obj(response)["id"])


def _sync(
    client: TestClient[Litestar], instance_id: str, *, full: bool = False
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/mirror/sync/{instance_id}?full={'true' if full else 'false'}",
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return json_obj(response)


def _sync_wanted(client: TestClient[Litestar], instance_id: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/mirror/sync/{instance_id}/wanted", headers=csrf_headers(client)
    )
    assert response.status_code == 201, response.text
    return json_obj(response)


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

        series = json_obj(client.get("/api/v1/mirror/series"))
        assert series["total"] == 3
        titles = [as_obj(row)["title"] for row in as_list(series["items"])]
        # sort_title ordering: "Alpha Show", "The Beta Show" (beta), "Gamma"
        assert titles == ["Alpha Show", "The Beta Show", "Gamma"]

    def test_sync_is_idempotent(
        self, client: TestClient[Litestar], instance_id: str
    ) -> None:
        _ = _sync(client, instance_id)
        _ = _sync(client, instance_id)
        series = json_obj(client.get("/api/v1/mirror/series"))
        assert series["total"] == 3
        movies = json_obj(client.get("/api/v1/mirror/movies"))
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
        series = json_obj(client.get("/api/v1/mirror/series"))
        assert series["total"] == 2
        assert all(
            as_obj(row)["title"] != "Alpha Show" for row in as_list(series["items"])
        )

    def test_episode_drilldown_with_subtitles(
        self, client: TestClient[Litestar], instance_id: str
    ) -> None:
        _ = _sync(client, instance_id)
        _ = _sync_wanted(client, instance_id)
        series = json_obj(client.get("/api/v1/mirror/series?search=alpha"))
        assert series["total"] == 1
        series_row = as_obj(as_list(series["items"])[0])
        episodes = json_obj(
            client.get(f"/api/v1/mirror/series/{series_row['id']}/episodes")
        )
        assert episodes["total"] == 4
        first = as_obj(as_list(episodes["items"])[0])
        assert first["season"] == 1
        assert [as_obj(s)["language"] for s in as_list(first["subtitles"])] == ["en"]
        assert [as_obj(w)["language"] for w in as_list(first["wanted"])] == ["da"]


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
        runs = json_obj(
            client.get(f"/api/v1/mirror/sync-runs?instance_id={instance_id}")
        )
        run_items = [as_obj(r) for r in as_list(runs["items"])]
        wanted_runs = [r for r in run_items if r["kind"] == "wanted"]
        assert len(wanted_runs) == 2
        assert all(r["status"] == "completed" for r in wanted_runs)


class TestBrowseAndDashboard:
    def test_missing_language_filter(
        self, client: TestClient[Litestar], instance_id: str
    ) -> None:
        _ = _sync(client, instance_id)
        _ = _sync_wanted(client, instance_id)
        missing_da = json_obj(client.get("/api/v1/mirror/series?missing_language=da"))
        assert missing_da["total"] == 2  # Gamma seeded with no missing languages
        missing_de = json_obj(client.get("/api/v1/mirror/series?missing_language=de"))
        assert missing_de["total"] == 0

    def test_coverage_stats(
        self, client: TestClient[Litestar], instance_id: str
    ) -> None:
        _ = _sync(client, instance_id)
        _ = _sync_wanted(client, instance_id)
        coverage: dict[str, dict[str, object]] = {}
        for entry in json_list(client.get("/api/v1/mirror/coverage")):
            row = as_obj(entry)
            language = row["language"]
            assert isinstance(language, str)
            coverage[language] = row
        assert coverage["en"]["episodesWithSubtitle"] == 9
        assert coverage["en"]["moviesWithSubtitle"] == 2
        assert coverage["da"]["episodesWanted"] == 7
        assert coverage["da"]["moviesWanted"] == 1

    def test_freshness(self, client: TestClient[Litestar], instance_id: str) -> None:
        stale = json_list(client.get("/api/v1/mirror/freshness"))
        assert as_obj(stale[0])["stale"] is True
        _ = _sync(client, instance_id)
        fresh = as_obj(json_list(client.get("/api/v1/mirror/freshness"))[0])
        assert fresh["stale"] is False
        assert fresh["lastFullSyncAt"] is not None
