"""Per-instance serialization for background passes.

Discovery and reconciliation may be triggered concurrently for the same
Bazarr instance (periodic loops + the wanted-sync completion hook). Their
ledger writes are individually safe, but interleaved passes can race the
SELECT-then-INSERT upsert and clobber each other's freshly-committed state.
One shared registry per process, created at app assembly, serializes passes
per instance while keeping different instances concurrent.

Single-process by design: multi-replica deployments would need a DB-level
lock (e.g. advisory locks) instead — out of scope for the shipped
single-container topology (NFR-3).
"""

import asyncio
from uuid import UUID


class InstanceLockRegistry:
    def __init__(self) -> None:
        self._locks: dict[UUID, asyncio.Lock] = {}

    def lock_for(self, instance_id: UUID) -> asyncio.Lock:
        lock = self._locks.get(instance_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[instance_id] = lock
        return lock
