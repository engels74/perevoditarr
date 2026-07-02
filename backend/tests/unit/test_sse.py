import asyncio

import msgspec

from perevoditarr.core.sse import SseBus, parse_topics


async def _collect_one(bus: SseBus, topics: frozenset[str] | None) -> object:
    stream = bus.stream(topics)
    message = await anext(stream)
    await stream.aclose()
    return message


async def test_publish_reaches_unfiltered_subscriber() -> None:
    bus = SseBus()
    task = asyncio.create_task(_collect_one(bus, None))
    await asyncio.sleep(0)  # let the subscriber register
    bus.publish("mirror.sync", {"progress": 42})
    message = await asyncio.wait_for(task, timeout=1)
    assert getattr(message, "event", None) == "mirror.sync"
    data = getattr(message, "data", None)
    assert isinstance(data, str)
    assert msgspec.json.decode(data.encode()) == {"progress": 42}


async def test_topic_filter_exact_and_prefix() -> None:
    bus = SseBus()
    task = asyncio.create_task(_collect_one(bus, frozenset({"instances"})))
    await asyncio.sleep(0)
    bus.publish("mirror.sync", {"n": 1})  # filtered out
    bus.publish("instances.health", {"ok": True})  # prefix match
    message = await asyncio.wait_for(task, timeout=1)
    assert getattr(message, "event", None) == "instances.health"


async def test_subscriber_cleanup_on_close() -> None:
    bus = SseBus()
    task = asyncio.create_task(_collect_one(bus, None))
    await asyncio.sleep(0)
    assert bus.subscriber_count == 1
    bus.publish("x", {})
    _ = await asyncio.wait_for(task, timeout=1)
    assert bus.subscriber_count == 0


def test_parse_topics() -> None:
    assert parse_topics(None) is None
    assert parse_topics("") is None
    assert parse_topics(" a, b ,") == frozenset({"a", "b"})
