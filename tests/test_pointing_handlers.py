from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_update(
    user_id: int = 111,
    chat_id: int = 999,
    first_name: str = "Host",
    topic_id: int | None = 1,
    args: list[str] | None = None,
    is_private: bool = False,
):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.first_name = first_name
    update.effective_chat.id = chat_id
    update.effective_chat.type = "private" if is_private else "supergroup"
    update.message.message_thread_id = topic_id
    update.message.reply_text = AsyncMock()
    return update


def _make_context(args: list[str] | None = None):
    context = MagicMock()
    context.args = args or []
    context.bot_data = {"pointing_rooms": {}}
    context.bot.send_message = AsyncMock()
    context.job_queue = MagicMock()
    context.job_queue.run_once = MagicMock()
    return context


class TestCmdCreateRoom:
    @pytest.mark.asyncio
    async def test_creates_room_and_replies_with_id(self):
        from src.pointing_handlers import cmd_create_room

        update = _make_update(user_id=111, chat_id=999, topic_id=1)
        context = _make_context()

        await cmd_create_room(update, context)

        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "Room" in reply_text or "room" in reply_text

        store = context.bot_data["pointing_rooms"]
        assert len(store) == 1


class TestCmdJoinRoom:
    @pytest.mark.asyncio
    async def test_join_valid_room(self):
        from src.pointing_handlers import cmd_join_room
        from src.pointing import create_room

        context = _make_context()
        store = context.bot_data["pointing_rooms"]
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)

        update_join = _make_update(
            user_id=222, chat_id=999, first_name="Alice", args=[room.room_id]
        )
        context.args = [room.room_id]

        await cmd_join_room(update_join, context)

        update_join.message.reply_text.assert_called_once()
        assert 222 in room.participants

    @pytest.mark.asyncio
    async def test_join_invalid_room_id(self):
        from src.pointing_handlers import cmd_join_room

        update = _make_update(user_id=222, chat_id=999, args=["badid"])
        context = _make_context(args=["badid"])

        await cmd_join_room(update, context)

        reply_text = update.message.reply_text.call_args[0][0]
        assert "không tìm thấy" in reply_text.lower() or "không tồn tại" in reply_text.lower()


class TestCmdCancelRoom:
    @pytest.mark.asyncio
    async def test_host_can_cancel(self):
        from src.pointing_handlers import cmd_cancel_room
        from src.pointing import create_room

        context = _make_context()
        store = context.bot_data["pointing_rooms"]
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)

        update = _make_update(user_id=111, chat_id=999)
        context.args = [room.room_id]

        await cmd_cancel_room(update, context)

        assert room.room_id not in store

    @pytest.mark.asyncio
    async def test_non_host_cannot_cancel(self):
        from src.pointing_handlers import cmd_cancel_room
        from src.pointing import create_room

        context = _make_context()
        store = context.bot_data["pointing_rooms"]
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)

        update = _make_update(user_id=222, chat_id=999)
        context.args = [room.room_id]

        await cmd_cancel_room(update, context)

        assert room.room_id in store


class TestCmdStartPoint:
    @pytest.mark.asyncio
    async def test_start_point_sends_dm_to_participants(self):
        from src.pointing_handlers import cmd_start_point
        from src.pointing import create_room, join_room

        context = _make_context()
        store = context.bot_data["pointing_rooms"]
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        join_room(room, user_id=222)
        join_room(room, user_id=333)

        update = _make_update(user_id=111, chat_id=999)

        await cmd_start_point(update, context)

        assert context.bot.send_message.call_count == 2

    @pytest.mark.asyncio
    async def test_non_host_cannot_start(self):
        from src.pointing_handlers import cmd_start_point
        from src.pointing import create_room, join_room

        context = _make_context()
        store = context.bot_data["pointing_rooms"]
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        join_room(room, user_id=222)

        update = _make_update(user_id=222, chat_id=999)

        await cmd_start_point(update, context)

        assert context.bot.send_message.call_count == 0


class TestVoteCallback:
    @pytest.mark.asyncio
    async def test_vote_records_and_acks(self):
        from src.pointing_handlers import handle_vote_callback
        from src.pointing import create_room, join_room

        context = _make_context()
        store = context.bot_data["pointing_rooms"]
        room = create_room(store, host_id=111, chat_id=999, topic_id=1)
        join_room(room, user_id=222)

        query = MagicMock()
        query.from_user.id = 222
        query.from_user.first_name = "Alice"
        query.data = f"vote:{room.room_id}:5"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query

        await handle_vote_callback(update, context)

        query.answer.assert_called_once()
        assert room.votes[222] == 5
