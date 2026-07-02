"""Doctor API DTOs (P1-T6)."""

from datetime import datetime
from uuid import UUID

from perevoditarr.core.schemas import ApiStruct


class DoctorFindingRead(ApiStruct):
    id: UUID
    check_id: str
    severity: str
    message: str
    explanation: str
    fix_guidance: str
    bazarr_instance_id: UUID | None
    lingarr_instance_id: UUID | None
    data: dict[str, object] | None


class DoctorRunRead(ApiStruct):
    id: UUID
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    summary: dict[str, int] | None
    findings: list[DoctorFindingRead]
