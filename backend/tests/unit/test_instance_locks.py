"""Per-instance lock registry (review fix: background-pass serialization)."""

import asyncio
from uuid import uuid4

from perevoditarr.core.locks import InstanceLockRegistry


def test_same_instance_shares_one_lock() -> None:
    registry = InstanceLockRegistry()
    instance_id = uuid4()
    assert registry.lock_for(instance_id) is registry.lock_for(instance_id)


def test_different_instances_get_independent_locks() -> None:
    registry = InstanceLockRegistry()
    assert registry.lock_for(uuid4()) is not registry.lock_for(uuid4())


async def test_lock_serializes_same_instance_passes() -> None:
    registry = InstanceLockRegistry()
    instance_id = uuid4()
    running: list[str] = []

    async def pass_(name: str) -> None:
        async with registry.lock_for(instance_id):
            running.append(f"{name}:start")
            await asyncio.sleep(0)  # yield inside the critical section
            running.append(f"{name}:end")

    async with asyncio.TaskGroup() as tg:
        _ = tg.create_task(pass_("a"))
        _ = tg.create_task(pass_("b"))
    # Never interleaved: each pass's start is immediately followed by its end.
    assert running == ["a:start", "a:end", "b:start", "b:end"]
