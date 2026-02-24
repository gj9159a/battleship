import asyncio
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_type: str
    entity_id: str
    ruleset_id: str
    seq: int
    ts: str
    payload: dict

    def as_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "entity_id": self.entity_id,
            "ruleset_id": self.ruleset_id,
            "seq": self.seq,
            "ts": self.ts,
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[EventEnvelope]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[asyncio.Queue[EventEnvelope], _Subscriber] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue[EventEnvelope]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()
        with self._lock:
            self._subscribers[queue] = _Subscriber(loop=loop, queue=queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[EventEnvelope]) -> None:
        with self._lock:
            self._subscribers.pop(queue, None)

    def publish_sync(self, event_type: str, entity_id: str, ruleset_id: str, payload: dict) -> None:
        with self._lock:
            self._seq += 1
            envelope = EventEnvelope(
                event_type=event_type,
                entity_id=entity_id,
                ruleset_id=ruleset_id,
                seq=self._seq,
                ts=datetime.now(tz=UTC).isoformat(),
                payload=payload,
            )
            subscribers = tuple(self._subscribers.values())

        for subscriber in subscribers:
            try:
                subscriber.loop.call_soon_threadsafe(subscriber.queue.put_nowait, envelope)
            except RuntimeError:
                # Loop was closed; drop stale subscriber.
                self.unsubscribe(subscriber.queue)

    async def publish(self, event_type: str, entity_id: str, ruleset_id: str, payload: dict) -> None:
        self.publish_sync(event_type=event_type, entity_id=entity_id, ruleset_id=ruleset_id, payload=payload)

    async def stream(self, queue: asyncio.Queue[EventEnvelope]) -> AsyncIterator[dict]:
        while True:
            event = await queue.get()
            yield event.as_dict()
