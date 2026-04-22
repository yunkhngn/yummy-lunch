from src.pointing import PointingRoom, create_room, get_room, remove_room


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
