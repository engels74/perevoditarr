"""Bazarr integration public interface (P1-T3)."""

from perevoditarr.modules.integrations.bazarr.capabilities import (
    CapabilityProbe,
    detect_capabilities,
)
from perevoditarr.modules.integrations.bazarr.client import (
    MIN_BAZARR_VERSION,
    BazarrClient,
    ensure_supported_version,
    parse_version,
)

__all__ = [
    "MIN_BAZARR_VERSION",
    "BazarrClient",
    "CapabilityProbe",
    "detect_capabilities",
    "ensure_supported_version",
    "parse_version",
]
