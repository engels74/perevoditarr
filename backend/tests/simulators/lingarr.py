"""In-process Lingarr simulator (P1-T8).

The two behaviors that are the point of this simulator (P1-T8):
- faithful §6.4 dedup: an active (Pending/InProgress) request with the same
  MediaId + MediaType + Title + SourceLanguage + TargetLanguage makes
  POST /api/translate/content return HTTP 200 with an EMPTY ARRAY
- faithful §6.5 identity coarseness: for Episodes the incoming arrMediaId is
  resolved as if it were a Sonarr EPISODE id (it is actually the series id),
  so it usually resolves to the None sentinel and two concurrent episodes of
  one show are indistinguishable
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from litestar import Litestar, MediaType, Request, Response, get, post
from litestar.datastructures import State

type _Req = Request[object, object, State]

ACTIVE_STATUSES = ("Pending", "InProgress")

DEFAULT_SETTINGS: dict[str, str] = {
    "automation_enabled": "false",
    "translation_schedule": "0 4 * * *",
    "max_translations_per_run": "10",
    "translation_cycle": "true",
    "movie_age_threshold": "0",
    "show_age_threshold": "0",
    "service_type": "libretranslate",
    "source_languages": '[{"code":"en","name":"English"}]',
    "target_languages": '[{"code":"da","name":"Danish"}]',
    "language_code_format": "",
    "use_batch_translation": "true",
    "max_batch_size": "10000",
    "max_retries": "3",
    "retry_delay": "5",
    "retry_delay_multiplier": "2",
    "request_timeout": "300",
    "fix_overlapping_subtitles": "false",
    "strip_subtitle_formatting": "false",
    "preserve_line_breaks": "true",
    "subtitle_validation_enabled": "true",
    "subtitle_validation_maxfilesizebytes": "2097152",
    "subtitle_validation_maxsubtitlelength": "500",
    "subtitle_validation_minsubtitlelength": "1",
    "auth_enabled": "false",
    "api_key": "",
    "onboarding_completed": "true",
}


@dataclass
class SimTranslationRequest:
    id: int
    media_id: int | None
    title: str
    source_language: str
    target_language: str
    media_type: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None
    job_id: str | None = None

    def wire(self) -> dict[str, object]:
        return {
            "id": self.id,
            "jobId": self.job_id,
            "mediaId": self.media_id,
            "title": self.title,
            "sourceLanguage": self.source_language,
            "targetLanguage": self.target_language,
            "mediaType": self.media_type,
            "status": self.status,
            "completedAt": self.completed_at.isoformat() if self.completed_at else None,
            "errorMessage": self.error_message,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.created_at.isoformat(),
        }


@dataclass
class _FailureInjection:
    status_code: int = 500
    remaining: int = 0


class LingarrSimulator:
    def __init__(
        self,
        *,
        api_key: str = "lingarr-key",
        version: str = "1.2.4",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.version: str = version
        self.now: Callable[[], datetime] = now or (lambda: datetime.now(UTC))
        self.settings: dict[str, str] = dict(DEFAULT_SETTINGS)
        self.settings["api_key"] = api_key
        self.requests: dict[int, SimTranslationRequest] = {}
        self._next_id: int = 0
        # §6.5: mapping of Sonarr EPISODE id -> internal media id. Bazarr sends
        # the SERIES id, which is (almost) never a valid episode id, so lookups
        # fall through to the None sentinel by default.
        self.episodes_by_sonarr_episode_id: dict[int, int] = {}
        self.movies_by_radarr_id: dict[int, int] = {}
        self._failure: _FailureInjection = _FailureInjection()
        # keep content requests in-flight (InProgress, no lines returned yet)?
        # not needed for P1; the content endpoint completes synchronously like
        # upstream (Bazarr holds the HTTP connection).
        self.app: Litestar = self._build_app()

    # ----------------------------------------------------------- controls

    @property
    def api_key(self) -> str:
        return self.settings["api_key"]

    def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    def inject_content_failure(self, *, status_code: int = 500, count: int = 1) -> None:
        self._failure = _FailureInjection(status_code=status_code, remaining=count)

    def add_request(
        self,
        *,
        media_id: int | None,
        title: str,
        source_language: str,
        target_language: str,
        media_type: str,
        status: str,
    ) -> SimTranslationRequest:
        self._next_id += 1
        record = SimTranslationRequest(
            id=self._next_id,
            media_id=media_id,
            title=title,
            source_language=source_language,
            target_language=target_language,
            media_type=media_type,
            status=status,
            created_at=self.now(),
        )
        self.requests[record.id] = record
        return record

    # ---------------------------------------------------------------- app

    def _denied(self, request: _Req) -> Response[dict[str, object]] | None:
        if self.settings.get("onboarding_completed") != "true":
            return Response(
                {"message": "Onboarding required", "onboardingRequired": True},
                status_code=403,
            )
        if self.settings.get("auth_enabled") != "true":
            return None
        if request.headers.get("X-Api-Key") == self.settings.get("api_key"):
            return None
        return Response(
            {"message": "Authentication required", "authenticated": False},
            status_code=401,
        )

    def _build_app(self) -> Litestar:
        sim = self

        @get("/api/version", sync_to_thread=False)
        def version(request: _Req) -> Response[dict[str, object]]:
            # [AllowAnonymous] upstream — no auth gate.
            _ = request
            return Response(
                {
                    "newVersion": False,
                    "isDevelopment": False,
                    "currentVersion": sim.version,
                    "latestVersion": sim.version,
                }
            )

        @get("/api/setting/{key:str}", sync_to_thread=False)
        def get_setting(request: _Req, key: str) -> Response[object]:
            if (denied := sim._denied(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            value = sim.settings.get(key)
            if value is None:
                return Response(
                    "Setting not found", status_code=400, media_type=MediaType.TEXT
                )
            # ASP.NET serializes ActionResult<string> as a quoted JSON string;
            # a raw str body would pass through Litestar unquoted.
            import msgspec

            return Response(msgspec.json.encode(value), media_type=MediaType.JSON)

        @post("/api/setting/multiple/get", status_code=200, sync_to_thread=False)
        def get_settings(request: _Req, data: list[str]) -> Response[dict[str, str]]:
            if (denied := sim._denied(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            return Response(
                {key: sim.settings[key] for key in data if key in sim.settings}
            )

        @get("/api/translationrequest/active", sync_to_thread=False)
        def active(request: _Req) -> Response[list[dict[str, object]]]:
            if (denied := sim._denied(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            return Response(
                [
                    {
                        "mediaId": r.media_id,
                        "mediaType": r.media_type,
                        "status": r.status,
                    }
                    for r in sim.requests.values()
                    if r.status in ACTIVE_STATUSES
                ]
            )

        @get("/api/translationrequest/requests", sync_to_thread=False)
        def requests_page(
            request: _Req,
            pageNumber: int = 1,
            pageSize: int = 20,
        ) -> Response[dict[str, object]]:
            if (denied := sim._denied(request)) is not None:
                return denied
            rows = sorted(sim.requests.values(), key=lambda r: -r.id)
            window = rows[(pageNumber - 1) * pageSize : pageNumber * pageSize]
            return Response(
                {
                    "items": [r.wire() for r in window],
                    "totalCount": len(rows),
                    "pageNumber": pageNumber,
                    "pageSize": pageSize,
                }
            )

        @get("/api/translationrequest/{request_id:int}", sync_to_thread=False)
        def request_detail(
            request: _Req, request_id: int
        ) -> Response[dict[str, object] | None]:
            if (denied := sim._denied(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            record = sim.requests.get(request_id)
            if record is None:
                return Response(None, status_code=404)
            return Response(record.wire())

        def _action(
            request: _Req, data: dict[str, object], new_status: str | None
        ) -> Response[object]:
            if (denied := sim._denied(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            record = sim.requests.get(int(str(data.get("id", 0))))
            if record is None:
                return Response(None, status_code=404)
            if new_status is not None:
                record.status = new_status
            return Response(record.wire())

        @post("/api/translationrequest/cancel", status_code=200, sync_to_thread=False)
        def cancel(request: _Req, data: dict[str, object]) -> Response[object]:
            return _action(request, data, "Cancelled")

        @post("/api/translationrequest/remove", status_code=200, sync_to_thread=False)
        def remove(request: _Req, data: dict[str, object]) -> Response[object]:
            if (denied := sim._denied(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            record = sim.requests.pop(int(str(data.get("id", 0))), None)
            if record is None:
                return Response(None, status_code=404)
            return Response(record.wire())

        @post("/api/translationrequest/retry", status_code=200, sync_to_thread=False)
        def retry(request: _Req, data: dict[str, object]) -> Response[object]:
            if (denied := sim._denied(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            record = sim.requests.get(int(str(data.get("id", 0))))
            if record is None:
                return Response(None, status_code=404)
            fresh = sim.add_request(
                media_id=record.media_id,
                title=record.title,
                source_language=record.source_language,
                target_language=record.target_language,
                media_type=record.media_type,
                status="Pending",
            )
            return Response(fresh.wire())

        @post("/api/translationrequest/resume", status_code=200, sync_to_thread=False)
        def resume(request: _Req, data: dict[str, object]) -> Response[object]:
            return _action(request, data, "Pending")

        @get("/api/statistics", sync_to_thread=False)
        def statistics(request: _Req) -> Response[dict[str, object]]:
            if (denied := sim._denied(request)) is not None:
                return denied
            completed = [r for r in sim.requests.values() if r.status == "Completed"]
            return Response(
                {
                    "totalLinesTranslated": len(completed),
                    "totalFilesTranslated": len(completed),
                    "totalCharactersTranslated": len(completed) * 11,
                    "totalMovies": 0,
                    "totalEpisodes": 0,
                    "totalSubtitles": 0,
                    "translationsByMediaType": {},
                    "translationsByService": {},
                    "subtitlesByLanguage": {},
                }
            )

        @get("/api/schedule/jobs", sync_to_thread=False)
        def schedule_jobs(request: _Req) -> Response[list[dict[str, object]]]:
            if (denied := sim._denied(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            return Response(
                [
                    {
                        "jobId": "automation",
                        "cron": sim.settings.get("translation_schedule", ""),
                        "enabled": sim.settings.get("automation_enabled") == "true",
                    }
                ]
            )

        @post("/api/translate/content", status_code=200, sync_to_thread=False)
        def translate_content(
            request: _Req, data: dict[str, object]
        ) -> Response[object]:
            if (denied := sim._denied(request)) is not None:
                return denied  # pyright: ignore[reportReturnType]
            if sim._failure.remaining > 0:
                sim._failure.remaining -= 1
                return Response(
                    {"error": "injected failure"},
                    status_code=sim._failure.status_code,
                )

            arr_media_id = int(str(data["arrMediaId"]))
            media_type = str(data["mediaType"])
            title = str(data["title"])
            source = str(data["sourceLanguage"])
            target = str(data["targetLanguage"])
            lines_raw = data.get("lines")
            lines: list[dict[str, object]] = (
                cast("list[dict[str, object]]", lines_raw)
                if isinstance(lines_raw, list)
                else []
            )

            # §6.5: Episode arrMediaId (actually the series id) is resolved as
            # a Sonarr EPISODE id -> None sentinel almost always.
            if media_type == "Episode":
                media_id = sim.episodes_by_sonarr_episode_id.get(arr_media_id)
            else:
                media_id = sim.movies_by_radarr_id.get(arr_media_id, arr_media_id)

            # §6.4 dedup: active identical identity => HTTP 200, EMPTY ARRAY.
            for record in sim.requests.values():
                if (
                    record.media_id == media_id
                    and record.media_type == media_type
                    and record.title == title
                    and record.source_language == source
                    and record.target_language == target
                    and record.status in ACTIVE_STATUSES
                ):
                    return Response([])

            record = sim.add_request(
                media_id=media_id,
                title=title,
                source_language=source,
                target_language=target,
                media_type=media_type,
                status="InProgress",
            )
            translated = [
                {
                    "position": int(str(line.get("position", 0))),
                    "line": f"[{target}] {line.get('line', '')}",
                }
                for line in lines
            ]
            record.status = "Completed"
            record.completed_at = sim.now()
            return Response(translated)

        return Litestar(
            route_handlers=[
                version,
                get_setting,
                get_settings,
                active,
                requests_page,
                request_detail,
                cancel,
                remove,
                retry,
                resume,
                statistics,
                schedule_jobs,
                translate_content,
            ],
            openapi_config=None,
        )
