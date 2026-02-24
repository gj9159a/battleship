import asyncio
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


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[EventEnvelope]] = set()
        self._seq = 0

    def subscribe(self) -> asyncio.Queue[EventEnvelope]:
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[EventEnvelope]) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event_type: str, entity_id: str, ruleset_id: str, payload: dict) -> None:
        self._seq += 1
        envelope = EventEnvelope(
            event_type=event_type,
            entity_id=entity_id,
            ruleset_id=ruleset_id,
            seq=self._seq,
            ts=datetime.now(tz=UTC).isoformat(),
            payload=payload,
        )
        for queue in tuple(self._subscribers):
            await queue.put(envelope)

    async def stream(self, queue: asyncio.Queue[EventEnvelope]) -> AsyncIterator[dict]:
        while True:
            event = await queue.get()
            yield event.as_dict()
