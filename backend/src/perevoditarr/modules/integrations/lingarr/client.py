"""Lingarr API client (P1-T3).

Read/observe plus user-initiated request actions (cancel/retry/resume/remove,
FR-X3) ONLY. This client deliberately has no method for
POST /api/translate/content — that is Bazarr's write path (PRD §7.5/§6.3);
calling it from Perevoditarr would bypass Bazarr tracking.

Version pin: MIN_LINGARR_VERSION resolves PRD open question #2 — 1.2.4 is the
release line validated by code research (main branch, May 2026).
"""

import msgspec
from httpx import AsyncClient, HTTPError, Response

from perevoditarr.core.errors import (
    UnsupportedVersionError,
    UpstreamError,
    UpstreamUnavailableError,
)
from perevoditarr.modules.integrations.bazarr.client import parse_version
from perevoditarr.modules.integrations.lingarr.schemas import (
    ActiveTranslation,
    LingarrStatistics,
    PagedTranslationRequests,
    TranslationRequestRecord,
    VersionInfo,
)

type _Params = dict[str, str | int | bool | list[int]]

MIN_LINGARR_VERSION = (1, 2, 4)

API_KEY_HEADER = "X-Api-Key"

# The exact key set the doctor reads (FR-DR checks); Lingarr's settings are
# authoritative (§6.7) — Perevoditarr never writes them (N4).
DOCTOR_SETTING_KEYS = (
    "automation_enabled",
    "translation_schedule",
    "max_translations_per_run",
    "translation_cycle",
    "movie_age_threshold",
    "show_age_threshold",
    "service_type",
    "source_languages",
    "target_languages",
    "language_code_format",
    "use_batch_translation",
    "max_batch_size",
    "max_retries",
    "retry_delay",
    "retry_delay_multiplier",
    "request_timeout",
    "fix_overlapping_subtitles",
    "subtitle_validation_enabled",
    "subtitle_validation_maxfilesizebytes",
    "subtitle_validation_maxsubtitlelength",
    "subtitle_validation_minsubtitlelength",
)


def ensure_supported_version(raw: str) -> tuple[int, ...]:
    version = parse_version(raw)
    if version < MIN_LINGARR_VERSION:
        minimum = ".".join(str(p) for p in MIN_LINGARR_VERSION)
        raise UnsupportedVersionError(
            f"Lingarr {raw} is not supported: Perevoditarr requires >= {minimum} "
            "(the release line validated during integration research)"
        )
    return version


class LingarrClient:
    def __init__(self, http: AsyncClient) -> None:
        self.http: AsyncClient = http

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: _Params | None = None,
        json_body: object | None = None,
        ok_statuses: tuple[int, ...] = (200,),
    ) -> Response:
        try:
            response = await self.http.request(
                method, path, params=params, json=json_body
            )
        except HTTPError as error:
            raise UpstreamUnavailableError(
                f"Lingarr request failed: {error}"
            ) from error
        if response.status_code not in ok_statuses:
            raise UpstreamError(
                f"Lingarr {method} {path} returned {response.status_code}"
            )
        return response

    def _decode[T](self, content: bytes, expected: type[T]) -> T:
        # Malformed upstream JSON is "Lingarr misbehaved" — translate it into the
        # domain error hierarchy here, the same way _request() translates
        # transport failures, so callers only ever handle PerevoditarrError.
        try:
            return msgspec.json.decode(content, type=expected)
        except msgspec.DecodeError as error:
            raise UpstreamError(f"Lingarr returned malformed JSON: {error}") from error

    # --- version & settings ------------------------------------------------

    async def version(self) -> VersionInfo:
        response = await self._request("GET", "/api/version")
        return self._decode(response.content, VersionInfo)

    async def get_setting(self, key: str) -> str | None:
        response = await self._request(
            "GET", f"/api/setting/{key}", ok_statuses=(200, 400)
        )
        if response.status_code != 200:
            return None
        return self._decode(response.content, str)

    async def get_settings(self, keys: tuple[str, ...]) -> dict[str, str]:
        response = await self._request(
            "POST", "/api/setting/multiple/get", json_body=list(keys)
        )
        return self._decode(response.content, dict[str, str])

    async def doctor_settings(self) -> dict[str, str]:
        return await self.get_settings(DOCTOR_SETTING_KEYS)

    # --- translation requests (durable execution detail, §6.8) --------------

    async def active_requests(self) -> list[ActiveTranslation]:
        response = await self._request("GET", "/api/translationrequest/active")
        return self._decode(response.content, list[ActiveTranslation])

    async def requests_page(
        self,
        *,
        page_number: int = 1,
        page_size: int = 20,
        search_query: str | None = None,
        order_by: str | None = None,
        ascending: bool = True,
    ) -> PagedTranslationRequests:
        params: _Params = {
            "pageNumber": page_number,
            "pageSize": page_size,
            "ascending": ascending,
        }
        if search_query is not None:
            params["searchQuery"] = search_query
        if order_by is not None:
            params["orderBy"] = order_by
        response = await self._request(
            "GET", "/api/translationrequest/requests", params=params
        )
        return self._decode(response.content, PagedTranslationRequests)

    async def request_detail(self, request_id: int) -> TranslationRequestRecord:
        response = await self._request(
            "GET", f"/api/translationrequest/{request_id}", ok_statuses=(200, 404)
        )
        if response.status_code == 404:
            raise UpstreamError(f"Lingarr translation request {request_id} not found")
        return self._decode(response.content, TranslationRequestRecord)

    # Pass-through actions (FR-X3): user-initiated, 1:1 with Lingarr's own
    # endpoints, always audit-logged by the caller.

    async def cancel_request(self, request: TranslationRequestRecord) -> None:
        _ = await self._request(
            "POST", "/api/translationrequest/cancel", json_body=_action_body(request)
        )

    async def retry_request(self, request: TranslationRequestRecord) -> None:
        _ = await self._request(
            "POST", "/api/translationrequest/retry", json_body=_action_body(request)
        )

    async def resume_request(self, request: TranslationRequestRecord) -> None:
        _ = await self._request(
            "POST", "/api/translationrequest/resume", json_body=_action_body(request)
        )

    async def remove_request(self, request: TranslationRequestRecord) -> None:
        _ = await self._request(
            "POST", "/api/translationrequest/remove", json_body=_action_body(request)
        )

    # --- observability -------------------------------------------------------

    async def statistics(self) -> LingarrStatistics:
        response = await self._request("GET", "/api/statistics")
        return self._decode(response.content, LingarrStatistics)

    async def schedule_jobs(self) -> list[dict[str, object]]:
        response = await self._request("GET", "/api/schedule/jobs")
        return self._decode(response.content, list[dict[str, object]])


def _action_body(request: TranslationRequestRecord) -> dict[str, object]:
    # Lingarr's action endpoints bind the full TranslationRequest entity; the
    # fields it actually needs are the id plus required entity members.
    return {
        "id": request.id,
        "title": request.title or "",
        "sourceLanguage": request.source_language or "",
        "targetLanguage": request.target_language or "",
        "mediaType": request.media_type or "Movie",
        "status": request.status or "Pending",
    }
