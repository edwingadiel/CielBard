"""Deterministic discrete-event primitives for the CielBard simulator.

The simulator advances time in integer microseconds and never depends on the
iteration order of a container for anything that reaches the output, so every
scheduled state change goes through :class:`EventQueue`.  Ordering is defined
purely by ``(t_us, priority, seq)`` -- never by the payload -- which keeps two
runs of the same :class:`~sim.runconfig.FightConfig` byte identical.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

__all__ = [
    "Event",
    "EventQueue",
    "PRIORITIES",
    "LOCK_END",
    "GCD_READY",
    "COOLDOWN_READY",
    "STATUS_EXPIRE",
    "SERVER_TICK",
    "AUTO_ATTACK",
    "ACTION_EXECUTE",
    "DOWNTIME_START",
    "DOWNTIME_END",
    "FIGHT_END",
]

LOCK_END = "lock_end"
GCD_READY = "gcd_ready"
COOLDOWN_READY = "cooldown_ready"
STATUS_EXPIRE = "status_expire"
SERVER_TICK = "server_tick"
AUTO_ATTACK = "auto_attack"
ACTION_EXECUTE = "action_execute"
DOWNTIME_START = "downtime_start"
DOWNTIME_END = "downtime_end"
FIGHT_END = "fight_end"

#: Event kind -> priority.  Lower runs first at equal time.  ``server_tick``
#: deliberately sorts before ``action_execute`` so a DoT applied on exactly the
#: microsecond of a tick does not tick immediately, which is what the game does.
PRIORITIES: Dict[str, int] = {
    LOCK_END: 10,
    GCD_READY: 10,
    COOLDOWN_READY: 10,
    STATUS_EXPIRE: 20,
    SERVER_TICK: 30,
    AUTO_ATTACK: 35,
    ACTION_EXECUTE: 40,
    DOWNTIME_START: 50,
    DOWNTIME_END: 50,
    FIGHT_END: 90,
}

DEFAULT_PRIORITY = 100


@dataclass(order=True)
class Event:
    """A scheduled state change. Ordering is (time, priority, seq) -- never by payload."""

    t_us: int
    priority: int
    seq: int
    kind: str = field(compare=False)
    payload: dict = field(compare=False, default_factory=dict)

    @property
    def t_s(self) -> float:
        """The event time in seconds."""
        return self.t_us / 1_000_000.0


class EventQueue:
    """A deterministic min-heap. Ties break by `priority` then insertion order."""

    __slots__ = ("_heap", "_seq")

    def __init__(self) -> None:
        """Create an empty queue."""
        self._heap: List[Event] = []
        self._seq: int = 0

    def push(self, t_us: int, kind: str, priority: int = DEFAULT_PRIORITY, **payload: Any) -> None:
        """Schedule `kind` at `t_us` microseconds with the given payload.

        `priority` breaks ties at equal times; insertion order breaks the rest.
        """
        seq = self._seq
        self._seq = seq + 1
        heapq.heappush(self._heap, Event(int(t_us), int(priority), seq, kind, payload))

    def push_kind(self, t_us: int, kind: str, **payload: Any) -> None:
        """Schedule `kind` using its canonical priority from :data:`PRIORITIES`."""
        self.push(t_us, kind, PRIORITIES.get(kind, DEFAULT_PRIORITY), **payload)

    def pop_due(self, t_us: int) -> Iterator[Event]:
        """Yield every event with `e.t_us <= t_us`, in order, including events pushed
        by handlers during iteration."""
        heap = self._heap
        while heap and heap[0].t_us <= t_us:
            yield heapq.heappop(heap)

    def peek_us(self) -> Optional[int]:
        """The time of the earliest queued event, or None when the queue is empty."""
        return self._heap[0].t_us if self._heap else None

    def clear(self) -> None:
        """Drop every queued event. The insertion counter keeps running."""
        self._heap.clear()

    def __len__(self) -> int:
        """The number of queued events."""
        return len(self._heap)
