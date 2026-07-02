"""Instances module public interface (P1-T4)."""

from perevoditarr.modules.instances.controllers import (
    InstancesController,
    provide_instances_service,
)
from perevoditarr.modules.instances.gateway import InstanceGateway, provide_gateway
from perevoditarr.modules.instances.health import (
    health_monitor_loop,
    run_health_sweep,
)
from perevoditarr.modules.instances.models import BazarrInstance, LingarrInstance
from perevoditarr.modules.instances.schemas import (
    BazarrCapabilities,
    BazarrInstanceRead,
    InstanceHealth,
    LingarrInstanceRead,
)
from perevoditarr.modules.instances.service import (
    InstancesService,
    bazarr_read,
    lingarr_read,
)

__all__ = [
    "BazarrCapabilities",
    "BazarrInstance",
    "BazarrInstanceRead",
    "InstanceGateway",
    "InstanceHealth",
    "InstancesController",
    "InstancesService",
    "LingarrInstance",
    "LingarrInstanceRead",
    "bazarr_read",
    "health_monitor_loop",
    "lingarr_read",
    "provide_gateway",
    "provide_instances_service",
    "run_health_sweep",
]
