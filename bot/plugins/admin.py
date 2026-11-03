
"""
Admin Panel & Controls Plugin (plugins/admin.py)
================================================
Restricted to `Config.ADMIN_IDS`:
- `/stats`: Total users, premium users, free users, total articles, YouTube summaries, and PDFs exported.
- `/broadcast`: Reply to any message (text, photo, video, document with inline buttons) to broadcast to all users.
- `/addpremium <user_id> <days>`: Manually grant premium access and notify the user.
- `/removepremium <user_id>`: Revoke premium status immediately.
- `/images`: List every screen and where its picture comes from.
- `/setimg <screen> [url]`: Set a screen's picture (reply to a photo, or pass an image URL).
- `/delimg <screen>`: Remove a custom picture (falls back to env / default).
"""

import asyncio
import html
import logging
import time
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    UserIsBlocked,
    PeerIdInvalid,
)
from config import Config
from database import db
from utils import images

logger = logging.getLogger(__name__)


def admin_only(_, __, message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in Config.ADMIN_IDS)


admin_filter = filters.create(admin_only)


@Client.on_message(filters.command("stats") & admin_filter)
async def stats_command_handler(client: Client, message: Message) -> None:
    stats = await db.get_stats()
    total_processed = (
        stats["articles_scraped"] + stats["youtube_summaries"]
    )

    text = (
        "📊 <b>CleanReader Bot — Real-Time System Statistics</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "👥 <b>User Base:</b>\n"
        f"• Total Registered Users: <code>{stats['total_users']:,}</code>\n"
        f"• 💎 Premium Subscribers: <code>{stats['premium_users']:,}</code>\n"
        f"• 🆓 Free Tier Users: <code>{stats['free_users']:,}</code>\n\n"
        "⚡ <b>Processing Metrics:</b>\n"
        f"• Total Links Processed: <code>{total_processed:,}</code>\n"
        f"• 📰 Clean Web Articles (Telegraph IV): <code>{stats['articles_scraped']:,}</code>\n"
        f"• 🎬 YouTube AI Summaries: <code>{stats['youtube_summaries']:,}</code>\n"
        f"• 📥 Clean PDFs Exported: <code>{stats['pdfs_exported']:,}</code>"
    )
    await message.reply_text(text, quote=True)


@Client.on_message(filters.command("addpremium") & admin_filter)
async def add_premium_command_handler(client: Client, message: Message) -> None:
    """Usage: /addpremium <user_id> <days>"""
    if len(message.command) < 3:
        await message.reply_text(
            "ℹ️ <b>Usage:</b> <code>/addpremium &lt;user_id&gt; &lt;days&gt;</code>\n"
            "Example: <code>/addpremium 582910421 30</code>",
            quote=True,
        )
        return

    try:
        target_user_id = int(message.command[1])
        days = int(message.command[2])
    except ValueError:
        await message.reply_text("❌ Both <code>user_id</code> and <code>days</code> must be integers.")
        return

    expiry = await db.grant_premium(target_user_id, days)
    expiry_str = expiry.strftime("%d %b %Y %H:%M UTC")

    await message.reply_text(
        "✅ <b>Premium Access Granted</b>\n\n"
        f"🆔 <b>User ID:</b> <code>{target_user_id}</code>\n"
        f"📅 <b>Days Added:</b> <code>{days}</code>\n"
        f"⏳ <b>Expires On:</b> <code>{expiry_str}</code>",
        quote=True,
    )

    try:
        await client.send_message(
            chat_id=target_user_id,
            text=(
                "🎉 <b>Your Account Has Been Upgraded to Premium!</b>\n\n"
                f"An administrator has granted you <b>{days} days</b> of CleanReader Premium.\n"
                f"⏳ <b>Valid Until:</b> <code>{expiry_str}</code>"
            ),
        )
    except Exception:
        pass


@Client.on_message(filters.command("removepremium") & admin_filter)
async def remove_premium_command_handler(client: Client, message: Message) -> None:
    """Usage: /removepremium <user_id>"""
    if len(message.command) < 2:
        await message.reply_text(
            "ℹ️ <b>Usage:</b> <code>/removepremium &lt;user_id&gt;</code>",
            quote=True,
        )
        return

    try:
        target_user_id = int(message.command[1])
    except ValueError:
        await message.reply_text("❌ <code>user_id</code> must be an integer.")
        return

    revoked = await db.revoke_premium(target_user_id)
    if revoked:
        await message.reply_text(
            f"✅ Premium status revoked for User ID <code>{target_user_id}</code>.",
            quote=True,
        )
        try:
            await client.send_message(
                chat_id=target_user_id,
                text="ℹ️ Your CleanReader Premium subscription has been ended by an administrator.",
            )
        except Exception:
            pass
    else:
        await message.reply_text(
            f"ℹ️ User <code>{target_user_id}</code> was not found or did not have active Premium.",
            quote=True,
        )


@Client.on_message(filters.command("broadcast") & admin_filter)
async def broadcast_command_handler(client: Client, message: Message) -> None:
    """
    Reply `/broadcast` to any message (text, photo, video, document with inline buttons)
    to copy and broadcast it to all registered users in MongoDB.
    """
    target_msg = message.reply_to_message
    if not target_msg:
        await message.reply_text(
            "📣 <b>Broadcast Instructions:</b>\n"
            "Reply <code>/broadcast</code> to any message (including photos, formatting, "
            "and inline buttons) to deliver it to all registered users.",
            quote=True,
        )
        return

    status = await message.reply_text("📣 <b>Starting Broadcast...</b>", quote=True)
    start_ts = time.time()
    sent = 0
    blocked = 0
    failed = 0

    async for uid in db.iter_all_user_ids():
        try:
            await target_msg.copy(chat_id=uid)
            sent += 1
        except FloodWait as exc:
            await asyncio.sleep(exc.value + 1)
            try:
                await target_msg.copy(chat_id=uid)
                sent += 1
            except Exception:
                failed += 1
        except (InputUserDeactivated, UserIsBlocked, PeerIdInvalid):
            blocked += 1
        except Exception as exc:
            logger.debug("Broadcast error for %s: %s", uid, exc)
            failed += 1

        if (sent + blocked + failed) % 50 == 0:
            try:
                await status.edit_text(
                    "📣 <b>Broadcast in Progress...</b>\n"
                    f"✅ Sent: <code>{sent}</code> | 🚫 Blocked: <code>{blocked}</code> | ❌ Failed: <code>{failed}</code>"
                )
            except Exception:
                pass
        await asyncio.sleep(0.05)

    elapsed = round(time.time() - start_ts, 1)
    await status.edit_text(
        "✅ <b>Broadcast Completed!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📬 <b>Delivered:</b> <code>{sent}</code>\n"
        f"🚫 <b>Blocked / Deactivated:</b> <code>{blocked}</code>\n"
        f"⚠️ <b>Failed:</b> <code>{failed}</code>\n"
        f"⏱ <b>Elapsed Time:</b> <code>{elapsed}s</code>"
    )


# ----------------------------------------------------------------------
# Custom screen images
# ----------------------------------------------------------------------
def _screens_help() -> str:
    return "\n".join(f"• <code>{k}</code> — {v}" for k, v in images.SCREENS.items())


@Client.on_message(filters.command("images") & admin_filter)
async def list_images_handler(client: Client, message: Message) -> None:
    lines = [f"• <code>{k}</code> — <b>{images.describe(k)}</b>" for k in images.SCREENS]
    await message.reply_text(
        "🖼 <b>Screen Images</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"
        + "\n".join(lines)
        + "\n\n<b>Set:</b> reply to a photo with <code>/setimg &lt;screen&gt;</code> "
        "or <code>/setimg &lt;screen&gt; &lt;url&gt;</code>\n"
        "<b>Remove:</b> <code>/delimg &lt;screen&gt;</code>\n\n"
        f"<b>Screens:</b>\n{_screens_help()}",
        quote=True,
    )


@Client.on_message(filters.command("setimg") & admin_filter)
async def set_image_handler(client: Client, message: Message) -> None:
    if len(message.command) < 2 or message.command[1].lower() not in images.SCREENS:
        await message.reply_text(
            "ℹ️ <b>Usage:</b> reply to a photo with <code>/setimg &lt;screen&gt;</code> "
            "or <code>/setimg &lt;screen&gt; &lt;image_url&gt;</code>\n\n"
            f"<b>Screens:</b>\n{_screens_help()}",
            quote=True,
        )
        return

    screen = message.command[1].lower()
    reply = message.reply_to_message
    if reply and reply.photo:
        image = reply.photo.file_id
    elif len(message.command) >= 3 and message.command[2].startswith(("http://", "https://")):
        image = message.command[2]
    else:
        await message.reply_text(
            "❌ Reply to a <b>photo</b> or give a direct <code>https://</code> image URL.",
            quote=True,
        )
        return

    await images.set_image(screen, image)
    await message.reply_text(
        f"✅ Image for <code>{screen}</code> updated.", quote=True
    )


@Client.on_message(filters.command("delimg") & admin_filter)
async def delete_image_handler(client: Client, message: Message) -> None:
    if len(message.command) < 2 or message.command[1].lower() not in images.SCREENS:
        await message.reply_text(
            f"ℹ️ <b>Usage:</b> <code>/delimg &lt;screen&gt;</code>\n\n{_screens_help()}",
            quote=True,
        )
        return
    screen = message.command[1].lower()
    await images.delete_image(screen)
    await message.reply_text(
        f"🗑 Custom image for <code>{screen}</code> removed (now: <b>{images.describe(screen)}</b>).",
        quote=True,
    )
  
