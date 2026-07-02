"""Per-instance capability detection slots (PRD §2.4 / §6.6 / FR-DR10).

Both capabilities are False for every released Bazarr/Lingarr pair today —
by design. If a future upstream release returns the job id from the translate
PATCH or forwards sonarr_episode_id to Lingarr, the version map below is the
single place that flips them; nothing in Perevoditarr may depend on them
being True before that release exists.
"""

import msgspec

from perevoditarr.modules.integrations.bazarr.client import parse_version


class CapabilityProbe(msgspec.Struct, kw_only=True, frozen=True):
    translate_returns_job_id: bool = False
    lingarr_receives_episode_id: bool = False


# (first Bazarr version that has the capability) -> capability flag; empty on
# purpose: no released version has either (validated against v1.5.6 source).
_TRANSLATE_RETURNS_JOB_ID_SINCE: tuple[int, ...] | None = None
_LINGARR_RECEIVES_EPISODE_ID_SINCE: tuple[int, ...] | None = None


def detect_capabilities(bazarr_version: str) -> CapabilityProbe:
    version = parse_version(bazarr_version)
    return CapabilityProbe(
        translate_returns_job_id=(
            _TRANSLATE_RETURNS_JOB_ID_SINCE is not None
            and version >= _TRANSLATE_RETURNS_JOB_ID_SINCE
        ),
        lingarr_receives_episode_id=(
            _LINGARR_RECEIVES_EPISODE_ID_SINCE is not None
            and version >= _LINGARR_RECEIVES_EPISODE_ID_SINCE
        ),
    )
