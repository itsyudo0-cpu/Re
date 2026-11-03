"""
Force Subscribe (FSUB) Middleware & Decorator
=============================================
Verifies that a user has joined Config.FSUB_CHANNEL_ID before executing
commands, scraping URLs, or downloading PDFs in Private Messages (PM).
In Telegram Groups, commands (/read, /summary) bypass PM FSUB or optionally
prompt inline.
"""

import logging
from functools import wraps
from typing import Callable, Any
from pyrogram import Client
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from pyrogram.enums import ChatType, ChatMemberStatus
from pyrogram.errors import (
    UserNotParticipant,
    ChatAdminRequired,
    PeerIdInvalid,
    FloodWait,
)
import asyncio
from config import Config
from utils.images import render

logger = logging.getLogger(__name__)

BANNED_MEMBER_STATUSES = {
    ChatMemberStatus.BANNED,
    ChatMemberStatus.LEFT,
    ChatMemberStatus.RESTRICTED,
}


async def is_user_subscribed(client: Client, user_id: int) -> bool:
    """
    Check if `user_id` is an active member of `Config.FSUB_CHANNEL_ID`.
    Admins in `Config.ADMIN_IDS` automatically pass.
    """
    if not Config.FSUB_CHANNEL_ID:
        return True
    if user_id in Config.ADMIN_IDS:
        return True

    try:
        member = await client.get_chat_member(Config.FSUB_CHANNEL_ID, user_id)
        if member.status in (
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.MEMBER,
        ):
            return True
        return False
    except UserNotParticipant:
        return False
    except FloodWait as exc:
        await asyncio.sleep(exc.value)
        return await is_user_subscribed(client, user_id)
    except (ChatAdminRequired, PeerIdInvalid) as exc:
        logger.warning(
            "FSUB verification warning (Bot may not be admin in %s): %s",
            Config.FSUB_CHANNEL_ID,
            exc,
        )
        # Fail-open only if channel is misconfigured so bot doesn't lock out everyone
        return True
    except Exception as exc:
        logger.error("Unexpected FSUB check error: %s", exc)
        return False


def get_fsub_keyboard() -> InlineKeyboardMarkup:
    """Return clean inline keyboard with [Join Channel] and [Try Again / Refresh]."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="📢 Join Official Channel",
                    url=Config.FSUB_INVITE_LINK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Try Again / Refresh",
                    callback_data="fsub_refresh",
                )
            ],
        ]
    )


FSUB_PROMPT_TEXT = (
    "🔒 <b>Channel Subscription Required</b>\n\n"
    "To keep <b>CleanReader & Media Summarizer Bot</b> fast and ad-free, "
    "you must be a member of our official updates channel before reading articles, "
    "summarizing YouTube videos, or exporting clean PDFs.\n\n"
    "1️⃣ Tap <b>Join Official Channel</b> below.\n"
    "2️⃣ Return here and tap <b>Try Again / Refresh</b>."
)


def force_subscribe(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator for Pyrogram Message & CallbackQuery handlers.
    Enforces channel membership in Private Chats (PM).
    """

    @wraps(func)
    async def wrapper(client: Client, update: Message | CallbackQuery, *args: Any, **kwargs: Any) -> Any:
        user = update.from_user
        if not user:
            return await func(client, update, *args, **kwargs)

        # Determine chat type (only enforce strict FSUB gate in PMs)
        chat = update.chat if isinstance(update, Message) else (update.message.chat if update.message else None)
        if chat and chat.type != ChatType.PRIVATE:
            return await func(client, update, *args, **kwargs)

        subscribed = await is_user_subscribed(client, user.id)
        if not subscribed:
            if isinstance(update, CallbackQuery):
                await update.answer(
                    "⚠️ You haven't joined the channel yet! Please join first.",
                    show_alert=True,
                )
                try:
                    await render(update, "fsub", FSUB_PROMPT_TEXT, get_fsub_keyboard())
                except Exception:
                    pass
            else:
                await render(update, "fsub", FSUB_PROMPT_TEXT, get_fsub_keyboard())
            return None

        return await func(client, update, *args, **kwargs)

    return wrapper
