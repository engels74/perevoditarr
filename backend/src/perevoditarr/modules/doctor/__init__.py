"""Doctor module public interface (P1-T6)."""

from perevoditarr.modules.doctor.checks import all_checks
from perevoditarr.modules.doctor.controllers import (
    DoctorController,
    provide_doctor_service,
)
from perevoditarr.modules.doctor.framework import (
    DoctorCheck,
    DoctorContext,
    Finding,
)
from perevoditarr.modules.doctor.models import DoctorFinding, DoctorRun
from perevoditarr.modules.doctor.schemas import DoctorFindingRead, DoctorRunRead
from perevoditarr.modules.doctor.service import DoctorService

__all__ = [
    "DoctorCheck",
    "DoctorContext",
    "DoctorController",
    "DoctorFinding",
    "DoctorFindingRead",
    "DoctorRun",
    "DoctorRunRead",
    "DoctorService",
    "Finding",
    "all_checks",
    "provide_doctor_service",
]
