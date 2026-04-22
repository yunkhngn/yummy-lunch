from __future__ import annotations

import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden
from telegram.ext import ContextTypes

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


async def cmd_start_point(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = _get_store(context)
    user = update.effective_user
    chat_id = update.effective_chat.id

    room = _find_room_by_host(store, user.id, chat_id)
    if room is None:
        await update.message.reply_text(
            "Không tìm thấy room nào của bạn. Dùng /create_room trước."
        )
        return

    if user.id != room.host_id:
        await update.message.reply_text("Chỉ host mới có thể bắt đầu đánh điểm.")
        return

    if not room.participants:
        await update.message.reply_text("Chưa có ai join room. Đợi mọi người join trước.")
        return

    room.votes = {}
    room.revealed = False
    room.last_activity = time.time()

    keyboard = [
        [
            InlineKeyboardButton(str(p), callback_data=f"vote:{room.room_id}:{p}")
            for p in POINT_OPTIONS
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    for uid in room.participants:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"Chọn điểm cho task (Room {room.room_id}):",
                reply_markup=reply_markup,
            )
        except Forbidden:
            logger.warning("Cannot DM user %s", uid)
        except Exception:
            logger.exception("Failed to DM user %s", uid)

    await update.message.reply_text(
        f"Đã gửi phiếu vote cho {len(room.participants)} người.\n"
        f"Tự động reveal sau {VOTE_TIMEOUT_SECONDS}s."
    )

    context.job_queue.run_once(
        _auto_reveal_callback,
        when=VOTE_TIMEOUT_SECONDS,
        data={"room_id": room.room_id},
        name=f"reveal_{room.room_id}",
    )


async def handle_vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("vote:"):
        return

    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 3:
        return

    _, room_id, point_str = parts
    try:
        point = int(point_str)
    except ValueError:
        return

    store = _get_store(context)
    room = get_room(store, room_id)
    if room is None:
        await query.edit_message_text("Room đã hết hạn hoặc bị huỷ.")
        return

    user_id = query.from_user.id
    ok = record_vote(room, user_id, point)
    if not ok:
        await query.edit_message_text("Vote không hợp lệ.")
        return

    await query.edit_message_text(f"Bạn đã vote {point} điểm!")

    if is_all_voted(room) and not room.revealed:
        await _reveal_results(room, context)


async def cmd_reveal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = _get_store(context)
    user = update.effective_user
    chat_id = update.effective_chat.id

    room = _find_room_by_host(store, user.id, chat_id)
    if room is None:
        await update.message.reply_text("Không tìm thấy room nào của bạn.")
        return

    if user.id != room.host_id:
        await update.message.reply_text("Chỉ host mới có thể reveal.")
        return

    await _reveal_results(room, context)


async def _reveal_results(room: PointingRoom, context: ContextTypes.DEFAULT_TYPE) -> None:
    if room.revealed:
        return
    room.revealed = True

    names: dict[int, str] = {}
    for uid in room.participants:
        try:
            chat = await context.bot.get_chat(uid)
            names[uid] = chat.first_name or f"User {uid}"
        except Exception:
            names[uid] = f"User {uid}"

    text = format_results(room, names)
    kwargs: dict = {"chat_id": room.chat_id, "text": text}
    if room.topic_id is not None:
        kwargs["message_thread_id"] = room.topic_id

    try:
        await context.bot.send_message(**kwargs)
    except Exception:
        logger.exception("Failed to send results to chat %s", room.chat_id)


async def _auto_reveal_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    room_id = context.job.data["room_id"]
    store = _get_store(context)
    room = get_room(store, room_id)
    if room is None or room.revealed:
        return
    await _reveal_results(room, context)


async def _cleanup_job_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    store = _get_store(context)
    expired = cleanup_expired_rooms(store, max_idle_seconds=ROOM_IDLE_SECONDS)
    if expired:
        logger.info("Cleaned up %d expired pointing rooms", len(expired))
