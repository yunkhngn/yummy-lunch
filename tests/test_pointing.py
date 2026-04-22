import time

from src.pointing import (
    POINT_OPTIONS,
    PointingRoom,
    cleanup_expired_rooms,
    create_room,
    format_results,
    get_room,
    is_all_voted,
    join_room,
    record_vote,
    remove_room,
)


class TestPointingRoom:
    def test_create_room_returns_room_with_id(self):
        store = {}
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        assert room.room_id in store
        assert room.host_id == 111
        assert room.chat_id == 999
        assert room.topic_id == 1
        assert room.participants == []
        assert room.votes == {}
        assert room.revealed is False


class TestJoinRoom:
    def test_join_adds_participant(self):
        store = {}
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        ok = join_room(room, user_id=222)
        assert ok is True
        assert 222 in room.participants

    def test_join_rejects_host(self):
        store = {}
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        ok = join_room(room, user_id=111)
        assert ok is False
        assert 111 not in room.participants

    def test_join_rejects_duplicate(self):
        store = {}
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        join_room(room, user_id=222)
        ok = join_room(room, user_id=222)
        assert ok is False
        assert room.participants.count(222) == 1


class TestRecordVote:
    def test_record_valid_vote(self):
        store = {}
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        join_room(room, user_id=222)
        ok = record_vote(room, user_id=222, point=5)
        assert ok is True
        assert room.votes[222] == 5

    def test_record_invalid_point_rejected(self):
        store = {}
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        join_room(room, user_id=222)
        ok = record_vote(room, user_id=222, point=4)
        assert ok is False
        assert 222 not in room.votes

    def test_record_non_participant_rejected(self):
        store = {}
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        ok = record_vote(room, user_id=999, point=5)
        assert ok is False


class TestIsAllVoted:
    def test_all_voted_true(self):
        store = {}
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        join_room(room, user_id=222)
        join_room(room, user_id=333)
        record_vote(room, user_id=222, point=5)
        record_vote(room, user_id=333, point=8)
        assert is_all_voted(room) is True

    def test_not_all_voted(self):
        store = {}
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        join_room(room, user_id=222)
        join_room(room, user_id=333)
        record_vote(room, user_id=222, point=5)
        assert is_all_voted(room) is False


class TestFormatResults:
    def test_format_with_votes(self):
        store = {}
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        join_room(room, user_id=222)
        join_room(room, user_id=333)
        record_vote(room, user_id=222, point=5)
        record_vote(room, user_id=333, point=8)
        names = {222: "Alice", 333: "Bob"}
        result = format_results(room, names)
        assert "Alice" in result
        assert "Bob" in result
        assert "6.5" in result

    def test_format_with_missing_votes(self):
        store = {}
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        join_room(room, user_id=222)
        join_room(room, user_id=333)
        record_vote(room, user_id=222, point=3)
        names = {222: "Alice", 333: "Bob"}
        result = format_results(room, names)
        assert "Alice" in result
        assert "Bob" in result
        assert "chưa vote" in result.lower() or "—" in result


class TestCleanupExpiredRooms:
    def test_removes_expired_rooms(self):
        store = {}
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        room.last_activity = time.time() - 120
        removed = cleanup_expired_rooms(store, max_idle_seconds=60)
        assert room.room_id not in store
        assert len(removed) == 1

    def test_keeps_active_rooms(self):
        store = {}
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        room.last_activity = time.time()
        removed = cleanup_expired_rooms(store, max_idle_seconds=60)
        assert room.room_id in store
        assert len(removed) == 0
