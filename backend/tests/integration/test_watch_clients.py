"""Watch-source client contract tests (P5-T1) against respx-mocked APIs."""

import httpx
import respx
from httpx import Request
from httpx import Response as MockResponse

from perevoditarr.modules.integrations.jellyfin import JellyfinClient
from perevoditarr.modules.integrations.plex import PlexClient
from perevoditarr.modules.integrations.tautulli import TautulliClient

TAUTULLI_URL = "http://tautulli:8181"
PLEX_URL = "http://plex:32400"
JELLYFIN_URL = "http://jellyfin:8096"
NOW = 1_720_000_000


async def test_tautulli_probe_and_activity() -> None:
    history = {
        "response": {
            "result": "success",
            "data": {
                "data": [
                    {
                        "date": NOW,
                        "media_type": "episode",
                        "grandparent_title": "The Office",
                        "full_title": "The Office - Pilot",
                        "group_count": 2,
                    },
                    {
                        "date": NOW - 100,
                        "media_type": "movie",
                        "title": "Dune",
                        "year": 2021,
                        "group_count": 1,
                    },
                    {"date": NOW, "media_type": "track", "title": "a song"},
                ]
            },
        }
    }
    server = {
        "response": {
            "result": "success",
            "data": {"pms_name": "HomePlex", "pms_version": "1.40"},
        }
    }

    def handler(request: Request) -> MockResponse:
        if request.url.params.get("cmd") == "get_server_info":
            return MockResponse(200, json=server)
        return MockResponse(200, json=history)

    async with respx.mock() as router:
        _ = router.get(f"{TAUTULLI_URL}/api/v2").mock(side_effect=handler)
        async with httpx.AsyncClient(base_url=TAUTULLI_URL) as http:
            client = TautulliClient(http, api_key="k")
            probe = await client.probe()
            activity = await client.fetch_activity(window_days=14, limit=100)

    assert probe.reachable and probe.identity == "HomePlex"
    shows = [a for a in activity if a.media_type == "show"]
    movies = [a for a in activity if a.media_type == "movie"]
    assert (
        len(shows) == 1 and shows[0].title == "The Office" and shows[0].play_count == 2
    )
    assert len(movies) == 1 and movies[0].year == 2021
    # tracks are ignored entirely
    assert len(activity) == 2


async def test_plex_history_and_watchlist() -> None:
    root = {"MediaContainer": {"friendlyName": "Home", "version": "1.40"}}
    history = {
        "MediaContainer": {
            "Metadata": [
                {"type": "episode", "grandparentTitle": "The Office", "viewedAt": NOW},
                {"type": "movie", "title": "Dune", "year": 2021, "viewedAt": NOW - 10},
            ]
        }
    }
    watchlist = {
        "MediaContainer": {
            "Metadata": [
                {"type": "show", "title": "Severance", "year": 2022},
                {"type": "movie", "title": "Arrival", "year": 2016},
            ]
        }
    }

    async with respx.mock() as router:
        _ = router.get(f"{PLEX_URL}/").mock(return_value=MockResponse(200, json=root))
        _ = router.get(f"{PLEX_URL}/status/sessions/history/all").mock(
            return_value=MockResponse(200, json=history)
        )
        _ = router.get(
            "https://discover.provider.plex.tv/library/sections/watchlist/all"
        ).mock(return_value=MockResponse(200, json=watchlist))
        async with httpx.AsyncClient(
            base_url=PLEX_URL,
            headers={"X-Plex-Token": "t", "Accept": "application/json"},
        ) as http:
            client = PlexClient(http, include_watchlist=True)
            probe = await client.probe()
            activity = await client.fetch_activity(window_days=14, limit=50)

    assert probe.reachable and probe.identity == "Home"
    watchlisted = {a.title for a in activity if a.watchlisted}
    assert watchlisted == {"Severance", "Arrival"}
    assert any(a.media_type == "show" and a.title == "The Office" for a in activity)


async def test_plex_watchlist_failure_is_best_effort() -> None:
    history: dict[str, object] = {"MediaContainer": {"Metadata": []}}
    async with respx.mock() as router:
        _ = router.get(f"{PLEX_URL}/status/sessions/history/all").mock(
            return_value=MockResponse(200, json=history)
        )
        _ = router.get(
            "https://discover.provider.plex.tv/library/sections/watchlist/all"
        ).mock(return_value=MockResponse(401))
        async with httpx.AsyncClient(
            base_url=PLEX_URL, headers={"X-Plex-Token": "t"}
        ) as http:
            client = PlexClient(http, include_watchlist=True)
            # A rejected watchlist must not raise — history still returns.
            activity = await client.fetch_activity(window_days=14, limit=50)
    assert activity == []


async def test_jellyfin_probe_and_activity() -> None:
    info = {"ServerName": "Media", "Version": "10.9"}
    users = [{"Id": "u1", "Name": "alice"}]
    items = {
        "Items": [
            {
                "Name": "Pilot",
                "Type": "Episode",
                "SeriesName": "The Office",
                "UserData": {
                    "PlayCount": 3,
                    "LastPlayedDate": "2024-07-01T12:00:00.0000000Z",
                },
            },
            {
                "Name": "Dune",
                "Type": "Movie",
                "ProductionYear": 2021,
                "UserData": {
                    "PlayCount": 1,
                    "LastPlayedDate": "2024-06-01T00:00:00.0000000Z",
                },
            },
        ],
        "TotalRecordCount": 2,
    }

    async with respx.mock() as router:
        _ = router.get(f"{JELLYFIN_URL}/System/Info").mock(
            return_value=MockResponse(200, json=info)
        )
        _ = router.get(f"{JELLYFIN_URL}/Users").mock(
            return_value=MockResponse(200, json=users)
        )
        _ = router.get(f"{JELLYFIN_URL}/Items").mock(
            return_value=MockResponse(200, json=items)
        )
        async with httpx.AsyncClient(
            base_url=JELLYFIN_URL,
            headers={"Authorization": 'MediaBrowser Token="k"'},
        ) as http:
            client = JellyfinClient(http, user="alice")
            probe = await client.probe()
            activity = await client.fetch_activity(window_days=14, limit=50)

    assert probe.reachable and probe.identity == "Media"
    show = next(a for a in activity if a.media_type == "show")
    assert show.title == "The Office" and show.play_count == 3
    assert show.last_watched_at is not None
    movie = next(a for a in activity if a.media_type == "movie")
    assert movie.year == 2021
