"""Typed Bazarr API response structs (P1-T3, PRD Appendix A).

Wire names follow Bazarr's mixed snake/camel convention exactly (validated
against the v1.5.6 line source); decoding stays tolerant of additive upstream
fields (forbid_unknown_fields defaults to False).
"""

import msgspec


class SubtitleLanguage(msgspec.Struct, kw_only=True):
    """`subtitles_language_model` — used by missing_subtitles everywhere."""

    name: str | None = None
    code2: str | None = None
    code3: str | None = None
    forced: bool = False
    hi: bool = False


class SubtitleFile(msgspec.Struct, kw_only=True):
    """`subtitles_model` — an existing subtitle; path None means embedded."""

    name: str | None = None
    code2: str | None = None
    code3: str | None = None
    path: str | None = None
    forced: bool = False
    hi: bool = False
    file_size: int | None = None


class AudioLanguage(msgspec.Struct, kw_only=True):
    name: str | None = None
    code2: str | None = None
    code3: str | None = None


class SystemStatusData(msgspec.Struct, kw_only=True):
    bazarr_version: str
    sonarr_version: str | None = None
    radarr_version: str | None = None
    operating_system: str | None = None
    python_version: str | None = None
    timezone: str | None = None
    start_time: float | None = None


class SystemStatusResponse(msgspec.Struct, kw_only=True):
    data: SystemStatusData


class GeneralSettings(msgspec.Struct, kw_only=True):
    concurrent_jobs: int | None = None
    upgrade_manual: bool | None = None
    use_sonarr: bool | None = None
    use_radarr: bool | None = None


class TranslatorSettings(msgspec.Struct, kw_only=True):
    translator_type: str | None = None
    lingarr_url: str | None = None
    lingarr_token: str | None = None


class SystemSettings(msgspec.Struct, kw_only=True):
    general: GeneralSettings | None = None
    translator: TranslatorSettings | None = None


class LanguageProfileItem(msgspec.Struct, kw_only=True):
    # Bazarr stores these as strings ("True"/"False") in the profile JSON.
    id: int | None = None
    language: str | None = None
    hi: str | bool | None = None
    forced: str | bool | None = None
    audio_exclude: str | bool | None = None


class LanguagesProfile(msgspec.Struct, kw_only=True):
    profile_id: int = msgspec.field(name="profileId")
    name: str
    cutoff: int | None = None
    items: list[LanguageProfileItem] = msgspec.field(default_factory=list)
    must_contain: list[str] = msgspec.field(name="mustContain", default_factory=list)
    must_not_contain: list[str] = msgspec.field(
        name="mustNotContain", default_factory=list
    )
    original_format: bool | None = msgspec.field(name="originalFormat", default=None)
    tag: str | None = None


class WantedEpisode(msgspec.Struct, kw_only=True):
    series_title: str | None = msgspec.field(name="seriesTitle", default=None)
    episode_number: str | None = None  # "1x3"
    episode_title: str | None = msgspec.field(name="episodeTitle", default=None)
    missing_subtitles: list[SubtitleLanguage] = msgspec.field(default_factory=list)
    sonarr_series_id: int = msgspec.field(name="sonarrSeriesId")
    sonarr_episode_id: int = msgspec.field(name="sonarrEpisodeId")
    scene_name: str | None = msgspec.field(name="sceneName", default=None)
    tags: list[str] = msgspec.field(default_factory=list)
    series_type: str | None = msgspec.field(name="seriesType", default=None)


class WantedEpisodesPage(msgspec.Struct, kw_only=True):
    data: list[WantedEpisode] = msgspec.field(default_factory=list)
    total: int = 0


class WantedMovie(msgspec.Struct, kw_only=True):
    title: str | None = None
    missing_subtitles: list[SubtitleLanguage] = msgspec.field(default_factory=list)
    radarr_id: int = msgspec.field(name="radarrId")
    scene_name: str | None = msgspec.field(name="sceneName", default=None)
    tags: list[str] = msgspec.field(default_factory=list)


class WantedMoviesPage(msgspec.Struct, kw_only=True):
    data: list[WantedMovie] = msgspec.field(default_factory=list)
    total: int = 0


class SeriesItem(msgspec.Struct, kw_only=True):
    sonarr_series_id: int = msgspec.field(name="sonarrSeriesId")
    title: str | None = None
    year: str | None = None
    monitored: bool = True
    ended: bool | None = None
    profile_id: int | None = msgspec.field(name="profileId", default=None)
    episode_file_count: int | None = msgspec.field(
        name="episodeFileCount", default=None
    )
    episode_missing_count: int | None = msgspec.field(
        name="episodeMissingCount", default=None
    )
    series_type: str | None = msgspec.field(name="seriesType", default=None)
    imdb_id: str | None = msgspec.field(name="imdbId", default=None)
    audio_language: list[AudioLanguage] | AudioLanguage | None = None
    tags: list[str] = msgspec.field(default_factory=list)


class SeriesPage(msgspec.Struct, kw_only=True):
    data: list[SeriesItem] = msgspec.field(default_factory=list)
    total: int = 0


class EpisodeItem(msgspec.Struct, kw_only=True):
    sonarr_series_id: int = msgspec.field(name="sonarrSeriesId")
    sonarr_episode_id: int = msgspec.field(name="sonarrEpisodeId")
    title: str | None = None
    season: int = 0
    episode: int = 0
    monitored: bool = True
    path: str | None = None
    scene_name: str | None = msgspec.field(name="sceneName", default=None)
    audio_language: list[AudioLanguage] | AudioLanguage | None = None
    subtitles: list[SubtitleFile] = msgspec.field(default_factory=list)
    missing_subtitles: list[SubtitleLanguage] = msgspec.field(default_factory=list)


class EpisodesResponse(msgspec.Struct, kw_only=True):
    data: list[EpisodeItem] = msgspec.field(default_factory=list)


class MovieItem(msgspec.Struct, kw_only=True):
    radarr_id: int = msgspec.field(name="radarrId")
    title: str | None = None
    year: str | None = None
    monitored: bool = True
    path: str | None = None
    scene_name: str | None = msgspec.field(name="sceneName", default=None)
    profile_id: int | None = msgspec.field(name="profileId", default=None)
    audio_language: list[AudioLanguage] | AudioLanguage | None = None
    subtitles: list[SubtitleFile] = msgspec.field(default_factory=list)
    missing_subtitles: list[SubtitleLanguage] = msgspec.field(default_factory=list)
    tags: list[str] = msgspec.field(default_factory=list)


class MoviesPage(msgspec.Struct, kw_only=True):
    data: list[MovieItem] = msgspec.field(default_factory=list)
    total: int = 0


class EpisodeHistoryItem(msgspec.Struct, kw_only=True):
    action: int
    timestamp: str | None = None
    sonarr_series_id: int | None = msgspec.field(name="sonarrSeriesId", default=None)
    sonarr_episode_id: int | None = msgspec.field(name="sonarrEpisodeId", default=None)
    series_title: str | None = msgspec.field(name="seriesTitle", default=None)
    episode_title: str | None = msgspec.field(name="episodeTitle", default=None)
    language: SubtitleLanguage | None = None
    subtitles_path: str | None = None
    description: str | None = None
    upgradable: bool | None = None


class EpisodeHistoryPage(msgspec.Struct, kw_only=True):
    data: list[EpisodeHistoryItem] = msgspec.field(default_factory=list)
    total: int = 0


class MovieHistoryItem(msgspec.Struct, kw_only=True):
    action: int
    timestamp: str | None = None
    radarr_id: int | None = msgspec.field(name="radarrId", default=None)
    title: str | None = None
    language: SubtitleLanguage | None = None
    subtitles_path: str | None = None
    description: str | None = None
    upgradable: bool | None = None


class MovieHistoryPage(msgspec.Struct, kw_only=True):
    data: list[MovieHistoryItem] = msgspec.field(default_factory=list)
    total: int = 0


# History action value meaning "translated" (bazarr history_log action=6).
HISTORY_ACTION_TRANSLATED = 6


class JobItem(msgspec.Struct, kw_only=True):
    job_id: int
    job_name: str | None = None
    status: str | None = None  # pending | running | failed | completed
    last_run_time: str | None = None
    is_progress: bool = False
    is_signalr: bool = False
    progress_value: int = 0
    progress_max: int = 0
    progress_message: str | None = None


class JobsResponse(msgspec.Struct, kw_only=True):
    data: list[JobItem] = msgspec.field(default_factory=list)
