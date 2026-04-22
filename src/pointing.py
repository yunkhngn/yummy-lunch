from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class PointingRoom:
    room_id: str
    host_id: int
    chat_id: int
    topic_id: int | None
    participants: list[int] = field(default_factory=list)
    votes: dict[int, int] = field(default_factory=dict)
    revealed: bool = False
    active: bool = True
    last_activity: float = field(default_factory=time.time)


def _generate_room_id() -> str:
    return uuid.uuid4().hex[:6]


def create_room(
    store: dict[str, PointingRoom],
    host_id: int,
    chat_id: int,
    topic_id: int | None = None,
) -> PointingRoom:
    room_id = _generate_room_id()
    room = PointingRoom(
        room_id=room_id,
        host_id=host_id,
        chat_id=chat_id,
        topic_id=topic_id,
    )
    store[room_id] = room
    return room


def get_room(store: dict[str, PointingRoom], room_id: str) -> PointingRoom | None:
    return store.get(room_id)


def remove_room(store: dict[str, PointingRoom], room_id: str) -> None:
    store.pop(room_id, None)
