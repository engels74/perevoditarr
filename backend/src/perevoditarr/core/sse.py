"""In-process SSE bus: modules publish, the UI subscribes at /api/v1/events.

This is the UI liveness plane only (FR-U7). Nothing on this bus may ever
drive a state transition (PRD §7.3) — durable evidence does that.
"""

import asyncio
import contextlib
from collections.abc import AsyncGenerator

import msgspec
from litestar import get
from litestar.response import ServerSentEvent
from litestar.response.sse import ServerSentEventMessage

HEARTBEAT_SECONDS = 15.0
_QUEUE_LIMIT = 256


class SseBus:
    def __init__(self) -> None:
        self._subscribers: dict[
            int, tuple[frozenset[str] | None, asyncio.Queue[ServerSentEventMessage]]
        ] = {}
        self._next_token: int = 0
        self._next_event_id: int = 0

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, topic: str, data: object) -> None:
        self._next_event_id += 1
        message = ServerSentEventMessage(
            data=msgspec.json.encode(data).decode("utf-8"),
            event=topic,
            id=str(self._next_event_id),
        )
        for topics, queue in self._subscribers.values():
            if topics is not None and not _matches(topic, topics):
                continue
            if queue.full():
                # Slow consumer: drop the oldest event. SSE is liveness, not
                # correctness (§7.3), so lossy delivery is acceptable.
                with contextlib.suppress(asyncio.QueueEmpty):
                    _ = queue.get_nowait()
            queue.put_nowait(message)

    async def stream(
        self, topics: frozenset[str] | None = None
    ) -> AsyncGenerator[ServerSentEventMessage]:
        queue: asyncio.Queue[ServerSentEventMessage] = asyncio.Queue(
            maxsize=_QUEUE_LIMIT
        )
        token = self._next_token
        self._next_token += 1
        self._subscribers[token] = (topics, queue)
        try:
            while True:
                try:
                    message = await asyncio.wait_for(
                        queue.get(), timeout=HEARTBEAT_SECONDS
                    )
                except TimeoutError:
                    yield ServerSentEventMessage(comment="heartbeat")
                else:
                    yield message
        finally:
            del self._subscribers[token]


def _matches(topic: str, subscribed: frozenset[str]) -> bool:
    # "mirror" subscribes to "mirror.sync", "mirror.freshness", ... as well.
    return topic in subscribed or any(
        topic.startswith(f"{prefix}.") for prefix in subscribed
    )


def parse_topics(raw: str | None) -> frozenset[str] | None:
    if raw is None:
        return None
    topics = frozenset(part.strip() for part in raw.split(",") if part.strip())
    return topics or None


@get("/events", include_in_schema=True, media_type="text/event-stream")
async def sse_events(sse_bus: SseBus, topics: str | None = None) -> ServerSentEvent:
    return ServerSentEvent(sse_bus.stream(parse_topics(topics)))
