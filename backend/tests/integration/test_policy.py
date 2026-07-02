"""Policy module end-to-end (P2-T1): presets, profiles, cascade, export/import."""

from collections.abc import Iterator
from typing import override

import httpx
import pytest
from litestar import Litestar
from litestar.testing import TestClient

from perevoditarr.core.http import HttpClientRegistry
from perevoditarr.modules.instances.gateway import InstanceGateway
from perevoditarr.modules.integrations.bazarr import BazarrClient
from perevoditarr.modules.integrations.lingarr import LingarrClient
from tests.conftest import complete_setup, csrf_headers
from tests.simulators.scenario import Scenario
from tests.support import as_list, as_obj, json_list, json_obj


class SimulatorGateway(InstanceGateway):
    """Routes gateway clients into the in-process simulators."""

    def __init__(self, scenario: Scenario) -> None:
        super().__init__(HttpClientRegistry())
        self.scenario: Scenario = scenario

    @override
    def bazarr(self, url: str, api_key: str) -> BazarrClient:
        transport = httpx.ASGITransport(app=self.scenario.bazarr.app)  # pyright: ignore[reportArgumentType]
        return BazarrClient(
            httpx.AsyncClient(
                transport=transport, base_url=url, headers={"X-API-KEY": api_key}
            )
        )

    @override
    def lingarr(self, url: str, api_key: str | None) -> LingarrClient:
        transport = httpx.ASGITransport(app=self.scenario.lingarr.app)  # pyright: ignore[reportArgumentType]
        headers = {"X-Api-Key": api_key} if api_key else None
        return LingarrClient(
            httpx.AsyncClient(transport=transport, base_url=url, headers=headers)
        )


@pytest.fixture
def scenario() -> Scenario:
    return Scenario()


@pytest.fixture
def client(app: Litestar, scenario: Scenario) -> Iterator[TestClient[Litestar]]:
    app.state["gateway"] = SimulatorGateway(scenario)
    with TestClient(app=app) as test_client:
        complete_setup(test_client)
        yield test_client


def _create_preset(
    client: TestClient[Litestar],
    name: str,
    *,
    dry_run: bool | None = None,
    targets: list[str] | None = None,
) -> dict[str, object]:
    values: dict[str, object] = {}
    if dry_run is not None:
        values["dryRun"] = dry_run
    if targets is not None:
        values["targetLanguages"] = targets
    response = client.post(
        "/api/v1/policy/presets",
        json={"name": name, "values": values},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return json_obj(response)


def _create_profile(
    client: TestClient[Litestar],
    name: str,
    *,
    targets: list[str],
    sources: list[str] | None = None,
) -> dict[str, object]:
    values: dict[str, object] = {"targetLanguages": targets}
    if sources is not None:
        values["sourcePreferences"] = sources
    response = client.post(
        "/api/v1/policy/profiles",
        json={"name": name, "values": values},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return json_obj(response)


def _register_bazarr(
    client: TestClient[Litestar], name: str = "main"
) -> dict[str, object]:
    response = client.post(
        "/api/v1/instances/bazarr",
        json={"name": name, "url": "http://bazarr.test", "apiKey": "bazarr-key"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return json_obj(response)


def _link_lingarr(
    client: TestClient[Litestar], bazarr_id: object, name: str = "lingarr-main"
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/instances/bazarr/{bazarr_id}/lingarr-discovery/confirm",
        json={"name": name},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return json_obj(response)


class TestPresets:
    def test_crud_and_single_active_invariant(
        self, client: TestClient[Litestar]
    ) -> None:
        first = _create_preset(client, "First", dry_run=True)
        second = _create_preset(client, "Second", dry_run=False)
        assert first["active"] is False and second["active"] is False

        activated = client.post(
            f"/api/v1/policy/presets/{first['id']}/activate",
            headers=csrf_headers(client),
        )
        assert json_obj(activated)["active"] is True

        _ = client.post(
            f"/api/v1/policy/presets/{second['id']}/activate",
            headers=csrf_headers(client),
        )
        listing = json_list(client.get("/api/v1/policy/presets"))
        active = [as_obj(p)["name"] for p in listing if as_obj(p)["active"] is True]
        assert active == ["Second"]

    def test_deleting_the_active_preset_conflicts(
        self, client: TestClient[Litestar]
    ) -> None:
        preset = _create_preset(client, "Solo")
        _ = client.post(
            f"/api/v1/policy/presets/{preset['id']}/activate",
            headers=csrf_headers(client),
        )
        response = client.delete(
            f"/api/v1/policy/presets/{preset['id']}", headers=csrf_headers(client)
        )
        assert response.status_code == 409

    def test_duplicate_name_conflicts(self, client: TestClient[Litestar]) -> None:
        _ = _create_preset(client, "Twice")
        response = client.post(
            "/api/v1/policy/presets",
            json={"name": "Twice"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 409

    def test_fork_copies_values(self, client: TestClient[Litestar]) -> None:
        source = _create_preset(client, "Origin", dry_run=False, targets=["da"])
        response = client.post(
            f"/api/v1/policy/presets/{source['id']}/fork",
            json={"name": "Copy"},
            headers=csrf_headers(client),
        )
        assert response.status_code == 201, response.text
        forked = json_obj(response)
        assert forked["name"] == "Copy"
        assert forked["builtIn"] is False and forked["active"] is False
        assert as_obj(forked["values"])["targetLanguages"] == ["da"]


class TestProfiles:
    def test_create_returns_inline_validation_findings(
        self, client: TestClient[Litestar]
    ) -> None:
        instance = _register_bazarr(client)
        _ = _link_lingarr(client, instance["id"])
        created = _create_profile(client, "Nordic", targets=["sv"], sources=["en"])
        codes = [as_obj(f)["code"] for f in as_list(created["findings"])]
        # Simulator wants en+da only; Lingarr serves en->da only.
        assert "target-not-wanted" in codes
        assert "target-not-in-lingarr" in codes

    def test_clean_profile_has_no_findings_against_simulator(
        self, client: TestClient[Litestar]
    ) -> None:
        instance = _register_bazarr(client)
        _ = _link_lingarr(client, instance["id"])
        created = _create_profile(client, "Danish", targets=["da"], sources=["en"])
        assert as_list(created["findings"]) == []

    def test_update_and_get_round_trip(self, client: TestClient[Litestar]) -> None:
        created = _create_profile(client, "Danish", targets=["da"])
        profile = as_obj(created["profile"])
        updated = client.patch(
            f"/api/v1/policy/profiles/{profile['id']}",
            json={"values": {"targetLanguages": ["da", "sv"]}},
            headers=csrf_headers(client),
        )
        assert updated.status_code == 200, updated.text
        fetched = json_obj(client.get(f"/api/v1/policy/profiles/{profile['id']}"))
        assert as_obj(as_obj(fetched["profile"])["values"])["targetLanguages"] == [
            "da",
            "sv",
        ]

    def test_source_equals_target_is_critical_finding(
        self, client: TestClient[Litestar]
    ) -> None:
        created = _create_profile(client, "Loop", targets=["en"], sources=["en"])
        severities = {
            as_obj(f)["code"]: as_obj(f)["severity"]
            for f in as_list(created["findings"])
        }
        assert severities.get("source-equals-target") == "critical"


class TestAssignmentsExclusionsOverrides:
    def test_assignment_lifecycle_and_scope_validation(
        self, client: TestClient[Litestar]
    ) -> None:
        instance = _register_bazarr(client)
        profile = as_obj(_create_profile(client, "Danish", targets=["da"])["profile"])
        created = client.post(
            "/api/v1/policy/assignments",
            json={
                "profileId": profile["id"],
                "bazarrInstanceId": instance["id"],
                "scopeType": "instance",
            },
            headers=csrf_headers(client),
        )
        assert created.status_code == 201, created.text

        duplicate = client.post(
            "/api/v1/policy/assignments",
            json={
                "profileId": profile["id"],
                "bazarrInstanceId": instance["id"],
                "scopeType": "instance",
            },
            headers=csrf_headers(client),
        )
        assert duplicate.status_code == 409

        bad_scope = client.post(
            "/api/v1/policy/assignments",
            json={
                "profileId": profile["id"],
                "bazarrInstanceId": instance["id"],
                "scopeType": "series",
                "scopeKey": "not-a-number",
            },
            headers=csrf_headers(client),
        )
        assert bad_scope.status_code == 422

        listing = json_list(
            client.get(
                "/api/v1/policy/assignments",
                params={"bazarr_instance_id": str(instance["id"])},
            )
        )
        assert len(listing) == 1
        assignment = as_obj(listing[0])
        assert assignment["profileName"] == "Danish"

        deleted = client.delete(
            f"/api/v1/policy/assignments/{assignment['id']}",
            headers=csrf_headers(client),
        )
        assert deleted.status_code == 204

    def test_exclusion_rule_key_validation_and_conflict(
        self, client: TestClient[Litestar]
    ) -> None:
        instance = _register_bazarr(client)
        good = client.post(
            "/api/v1/policy/exclusions",
            json={
                "bazarrInstanceId": instance["id"],
                "kind": "language_pair",
                "ruleKey": "en->da",
            },
            headers=csrf_headers(client),
        )
        assert good.status_code == 201, good.text

        duplicate = client.post(
            "/api/v1/policy/exclusions",
            json={
                "bazarrInstanceId": instance["id"],
                "kind": "language_pair",
                "ruleKey": "en->da",
            },
            headers=csrf_headers(client),
        )
        assert duplicate.status_code == 409

        malformed = client.post(
            "/api/v1/policy/exclusions",
            json={
                "bazarrInstanceId": instance["id"],
                "kind": "language_pair",
                "ruleKey": "en/da",
            },
            headers=csrf_headers(client),
        )
        assert malformed.status_code == 422

    def test_override_upsert_updates_in_place(
        self, client: TestClient[Litestar]
    ) -> None:
        instance = _register_bazarr(client)
        first = client.post(
            "/api/v1/policy/overrides",
            json={
                "bazarrInstanceId": instance["id"],
                "mediaType": "series",
                "mediaKey": "10",
                "values": {"dryRun": False},
            },
            headers=csrf_headers(client),
        )
        assert first.status_code == 201, first.text
        second = client.post(
            "/api/v1/policy/overrides",
            json={
                "bazarrInstanceId": instance["id"],
                "mediaType": "series",
                "mediaKey": "10",
                "values": {"dryRun": True},
            },
            headers=csrf_headers(client),
        )
        assert second.status_code == 201
        listing = json_list(
            client.get(
                "/api/v1/policy/overrides",
                params={"bazarr_instance_id": str(instance["id"])},
            )
        )
        assert len(listing) == 1
        assert as_obj(as_obj(listing[0])["values"])["dryRun"] is True


class TestEffectivePolicy:
    def test_provenance_across_all_layers(self, client: TestClient[Litestar]) -> None:
        instance = _register_bazarr(client)
        preset = _create_preset(client, "Active", dry_run=False, targets=["da"])
        _ = client.post(
            f"/api/v1/policy/presets/{preset['id']}/activate",
            headers=csrf_headers(client),
        )
        profile = as_obj(
            _create_profile(client, "Danish", targets=["da", "sv"])["profile"]
        )
        _ = client.post(
            "/api/v1/policy/assignments",
            json={
                "profileId": profile["id"],
                "bazarrInstanceId": instance["id"],
                "scopeType": "instance",
            },
            headers=csrf_headers(client),
        )
        _ = client.post(
            "/api/v1/policy/overrides",
            json={
                "bazarrInstanceId": instance["id"],
                "mediaType": "series",
                "mediaKey": "10",
                "values": {"targetLanguages": ["nb"]},
            },
            headers=csrf_headers(client),
        )

        effective = json_obj(
            client.get(
                "/api/v1/policy/effective",
                params={
                    "bazarr_instance_id": str(instance["id"]),
                    "media_type": "episode",
                    "sonarr_series_id": 10,
                    "sonarr_episode_id": 100,
                },
            )
        )
        targets = as_obj(effective["targetLanguages"])
        assert targets["value"] == ["nb"]
        assert as_obj(targets["provenance"])["layer"] == "override"

        dry_run = as_obj(effective["dryRun"])
        assert dry_run["value"] is False
        assert as_obj(dry_run["provenance"])["layer"] == "preset"
        assert as_obj(dry_run["provenance"])["sourceName"] == "Active"

        # A different series is untouched by the override.
        other = json_obj(
            client.get(
                "/api/v1/policy/effective",
                params={
                    "bazarr_instance_id": str(instance["id"]),
                    "media_type": "episode",
                    "sonarr_series_id": 11,
                    "sonarr_episode_id": 101,
                },
            )
        )
        other_targets = as_obj(other["targetLanguages"])
        assert other_targets["value"] == ["da", "sv"]
        assert as_obj(other_targets["provenance"])["layer"] == "profile"


class TestExportImport:
    def test_round_trip_skips_existing_and_creates_new(
        self, client: TestClient[Litestar]
    ) -> None:
        _ = _create_preset(client, "Mine", dry_run=False, targets=["da"])
        _ = _create_profile(client, "Danish", targets=["da"])

        exported = json_obj(client.get("/api/v1/policy/export"))
        assert exported["schemaVersion"] == 1
        assert [as_obj(p)["name"] for p in as_list(exported["presets"])] == ["Mine"]

        # Re-importing the same payload skips colliding names.
        reimport = json_obj(
            client.post(
                "/api/v1/policy/import",
                json=exported,
                headers=csrf_headers(client),
            )
        )
        assert reimport["createdPresets"] == []
        assert reimport["skipped"] == ["preset:Mine", "profile:Danish"]

        # Renamed payload creates fresh rows with identical values.
        renamed = {
            "schemaVersion": 1,
            "presets": [
                {**as_obj(p), "name": "Mine 2"} for p in as_list(exported["presets"])
            ],
            "profiles": [
                {**as_obj(p), "name": "Danish 2"} for p in as_list(exported["profiles"])
            ],
        }
        created = json_obj(
            client.post(
                "/api/v1/policy/import", json=renamed, headers=csrf_headers(client)
            )
        )
        assert created["createdPresets"] == ["Mine 2"]
        assert created["createdProfiles"] == ["Danish 2"]

        listing = json_list(client.get("/api/v1/policy/presets"))
        copy = next(as_obj(p) for p in listing if as_obj(p)["name"] == "Mine 2")
        assert as_obj(copy["values"])["targetLanguages"] == ["da"]
        assert copy["active"] is False  # imported posture never auto-activates

    def test_unsupported_schema_version_rejected(
        self, client: TestClient[Litestar]
    ) -> None:
        response = client.post(
            "/api/v1/policy/import",
            json={"schemaVersion": 99, "presets": [], "profiles": []},
            headers=csrf_headers(client),
        )
        assert response.status_code == 422
