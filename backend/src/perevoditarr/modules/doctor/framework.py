"""Doctor check framework (P1-T6).

Checks are pure: all upstream I/O happens once during context assembly
(service layer), so every check runs against a plain DoctorContext and is
unit-testable with fabricated fixtures. The doctor is read-only in v1 (N4).
"""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

import msgspec

from perevoditarr.modules.instances.schemas import BazarrCapabilities
from perevoditarr.modules.integrations.bazarr.schemas import (
    LanguagesProfile,
    SystemSettings,
)

type Severity = Literal["info", "warn", "critical"]

SEVERITIES: tuple[Severity, ...] = ("info", "warn", "critical")


class Finding(msgspec.Struct, kw_only=True):
    check_id: str
    severity: Severity
    message: str
    explanation: str
    fix_guidance: str
    bazarr_instance_id: UUID | None = None
    lingarr_instance_id: UUID | None = None
    data: dict[str, object] | None = None


class LingarrContext(msgspec.Struct, kw_only=True):
    instance_id: UUID | None = None
    url: str | None = None
    version: str | None = None
    reachable: bool = False
    # Doctor key set (§6.7 — Lingarr's settings are authoritative, never written).
    settings: dict[str, str] = msgspec.field(default_factory=dict)


class BazarrContext(msgspec.Struct, kw_only=True):
    instance_id: UUID
    name: str
    url: str
    version: str | None = None
    reachable: bool = False
    capabilities: BazarrCapabilities | None = None
    settings: SystemSettings | None = None
    profiles: list[LanguagesProfile] = msgspec.field(default_factory=list)
    lingarr: LingarrContext | None = None
    mirror_synced_ever: bool = False
    last_sync_finished_at: datetime | None = None


class DoctorContext(msgspec.Struct, kw_only=True):
    now: datetime
    instances: list[BazarrContext] = msgspec.field(default_factory=list)
    forward_auth_misconfigured: bool = False


class DoctorCheck(Protocol):
    check_id: str

    def run(self, context: DoctorContext) -> list[Finding]: ...


_REGISTRY: list[DoctorCheck] = []


def register[CheckT: DoctorCheck](check_cls: type[CheckT]) -> type[CheckT]:
    _REGISTRY.append(check_cls())
    return check_cls


def registered_checks() -> tuple[DoctorCheck, ...]:
    return tuple(_REGISTRY)
