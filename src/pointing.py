from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

POINT_OPTIONS: list[int] = [2, 3, 5, 8, 13]


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


def join_room(room: PointingRoom, user_id: int) -> bool:
    if user_id == room.host_id:
        return False
    if user_id in room.participants:
        return False
    room.participants.append(user_id)
    room.last_activity = time.time()
    return True


def record_vote(room: PointingRoom, user_id: int, point: int) -> bool:
    if user_id not in room.participants:
        return False
    if point not in POINT_OPTIONS:
        return False
    room.votes[user_id] = point
    room.last_activity = time.time()
    return True


def is_all_voted(room: PointingRoom) -> bool:
    return len(room.votes) == len(room.participants) and len(room.participants) > 0


def format_results(room: PointingRoom, names: dict[int, str]) -> str:
    lines = ["Sprint Pointing Results:", ""]
    for uid in room.participants:
        name = names.get(uid, f"User {uid}")
        point = room.votes.get(uid)
        if point is not None:
            lines.append(f"  - {name}: {point}")
        else:
            lines.append(f"  - {name}: —")
    voted_points = list(room.votes.values())
    if voted_points:
        avg = sum(voted_points) / len(voted_points)
        lines.append("")
        lines.append(f"Average: {avg:.1f}")
    return "\n".join(lines)


def cleanup_expired_rooms(
    store: dict[str, PointingRoom],
    max_idle_seconds: int = 60,
) -> list[PointingRoom]:
    now = time.time()
    expired = [
        room for room in store.values() if (now - room.last_activity) > max_idle_seconds
    ]
    for room in expired:
        store.pop(room.room_id, None)
    return expired
