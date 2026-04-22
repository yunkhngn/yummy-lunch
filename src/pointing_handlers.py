from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from src.pointing import PointingRoom, create_room, get_room, join_room, remove_room

logger = logging.getLogger(__name__)

ROOM_STORE_KEY = "pointing_rooms"
VOTE_TIMEOUT_SECONDS = 30
ROOM_IDLE_SECONDS = 60


def _get_store(context: ContextTypes.DEFAULT_TYPE) -> dict[str, PointingRoom]:
    if ROOM_STORE_KEY not in context.bot_data:
        context.bot_data[ROOM_STORE_KEY] = {}
    return context.bot_data[ROOM_STORE_KEY]


def _find_room_by_host(
    store: dict[str, PointingRoom], host_id: int, chat_id: int
) -> PointingRoom | None:
    for room in store.values():
        if room.host_id == host_id and room.chat_id == chat_id and room.active:
            return room
    return None


async def cmd_create_room(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = _get_store(context)
    user = update.effective_user
    chat_id = update.effective_chat.id
    topic_id = getattr(update.message, "message_thread_id", None)

    existing = _find_room_by_host(store, user.id, chat_id)
    if existing:
        await update.message.reply_text(
            f"Bạn đã có room đang mở: {existing.room_id}\n"
            "Dùng /cancel_room để huỷ trước khi tạo mới."
        )
        return

    room = create_room(store, host_id=user.id, chat_id=chat_id, topic_id=topic_id)
    await update.message.reply_text(
        f"Room Sprint Pointing đã tạo!\n"
        f"Room ID: {room.room_id}\n\n"
        f"Mọi người join bằng: /join_room {room.room_id}\n"
        f"Host dùng /start_point để bắt đầu đánh điểm."
    )


async def cmd_join_room(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = _get_store(context)
    user = update.effective_user

    if not context.args:
        await update.message.reply_text("Cú pháp: /join_room <room_id>")
        return

    room_id = context.args[0]
    room = get_room(store, room_id)
    if room is None:
        await update.message.reply_text("Room không tồn tại hoặc đã hết hạn.")
        return

    ok = join_room(room, user.id)
    if not ok:
        if user.id == room.host_id:
            await update.message.reply_text("Host không cần join room.")
        else:
            await update.message.reply_text("Bạn đã join room này rồi.")
        return

    count = len(room.participants)
    await update.message.reply_text(
        f"✅ {user.first_name} đã join room {room_id}! ({count} người tham gia)"
    )


async def cmd_cancel_room(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = _get_store(context)
    user = update.effective_user

    if not context.args:
        room = _find_room_by_host(store, user.id, update.effective_chat.id)
        if room is None:
            await update.message.reply_text("Không tìm thấy room nào của bạn.")
            return
    else:
        room_id = context.args[0]
        room = get_room(store, room_id)
        if room is None:
            await update.message.reply_text("Room không tồn tại.")
            return

    if user.id != room.host_id:
        await update.message.reply_text("Chỉ host mới có thể huỷ room.")
        return

    remove_room(store, room.room_id)
    await update.message.reply_text(f"Room {room.room_id} đã bị huỷ.")
