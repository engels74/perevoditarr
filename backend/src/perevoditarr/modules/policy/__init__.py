"""Policy module public interface (P2-T1).

Other modules import only from here: the cascade resolver types for
discovery/dispatch/doctor, the validation helpers for the doctor, and the
controller/DI for app wiring.
"""

from perevoditarr.modules.policy.controllers import (
    PolicyController,
    provide_policy_service,
)
from perevoditarr.modules.policy.resolver import (
    CODE2_CONVERSIONS,
    GLOBAL_DEFAULTS,
    CascadeInput,
    EffectivePolicy,
    EpisodeRef,
    ExclusionRule,
    ItemRef,
    LanguagePair,
    LanguagePairExclusion,
    MovieExclusion,
    MovieRef,
    PolicyValues,
    PriorityWeights,
    Provenance,
    Resolved,
    SeriesExclusion,
    SeriesRef,
    TagExclusion,
    match_exclusions,
    resolve_effective_policy,
)
from perevoditarr.modules.policy.schemas import RailSettingsDto
from perevoditarr.modules.policy.scoring import (
    ScoreBreakdown,
    ScoreFacts,
    score_intent,
)
from perevoditarr.modules.policy.service import PolicyService
from perevoditarr.modules.policy.validation import (
    LanguageInventory,
    PolicyFinding,
    ProfilePolicySummary,
    convert_code2,
    parse_lingarr_language_setting,
    validate_profile_values,
)

__all__ = [
    "CODE2_CONVERSIONS",
    "GLOBAL_DEFAULTS",
    "CascadeInput",
    "EffectivePolicy",
    "EpisodeRef",
    "ExclusionRule",
    "ItemRef",
    "LanguageInventory",
    "LanguagePair",
    "LanguagePairExclusion",
    "MovieExclusion",
    "MovieRef",
    "PolicyController",
    "PolicyFinding",
    "PolicyService",
    "PolicyValues",
    "PriorityWeights",
    "ProfilePolicySummary",
    "Provenance",
    "RailSettingsDto",
    "Resolved",
    "ScoreBreakdown",
    "ScoreFacts",
    "SeriesExclusion",
    "SeriesRef",
    "TagExclusion",
    "convert_code2",
    "match_exclusions",
    "parse_lingarr_language_setting",
    "provide_policy_service",
    "resolve_effective_policy",
    "score_intent",
    "validate_profile_values",
]
