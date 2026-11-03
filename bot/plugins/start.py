
"""
UI & Start Command Plugin (plugins/start.py)
============================================
- Renders the /start welcome screen with custom banner image (Config.START_IMG_URL)
- Inline keyboard buttons: "Help", "Premium Plans", "My Account", "Add to Group", "Support"
- Handles Force-Subscribe refresh callback (`fsub_refresh`)
"""

import html
from datetime import timezone
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from config import Config
from database import db
from utils.fsub import force_subscribe, is_user_subscribed
from utils.images import render


def build_start_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📖 Help", callback_data="nav_help"),
                InlineKeyboardButton("💎 Premium Plans", callback_data="nav_premium"),
            ],
            [
                InlineKeyboardButton("👤 My Account", callback_data="nav_account"),
                InlineKeyboardButton(
                    "➕ Add to Group",
                    url=f"https://t.me/{bot_username}?startgroup=true",
                ),
            ],
            [
                InlineKeyboardButton("💬 Support", url=Config.SUPPORT_CHAT_URL),
            ],
        ]
    )


def build_welcome_caption(first_name: str) -> str:
    safe_name = html.escape(first_name or "Reader")
    return (
        f"👋 <b>Welcome to CleanReader & Media Summarizer, {safe_name}!</b>\n\n"
        "Strip ads, popups, and paywalls from any article or extract executive "
        "AI takeaways from YouTube videos in seconds.\n\n"
        "⚡ <b>Core Capabilities:</b>\n"
        "• <b>Clean Web Reader:</b> Converts cluttered web links into instant <i>Telegraph Instant View</i> pages.\n"
        "• <b>YouTube Summarizer:</b> Extracts transcripts, key bullet points & timestamps.\n"
        "• <b>Gemini AI Synthesis:</b> 3-sentence TL;DR, key takeaways & estimated read time.\n"
        "• <b>One-Click PDF Export:</b> Download formatted, print-ready A4 PDFs.\n\n"
        "📩 <b>Send any URL or YouTube link here in PM</b>, or use <code>/read &lt;url&gt;</code> in Groups!"
    )


HELP_TEXT = (
    "📖 <b>How to Use CleanReader & Media Summarizer Bot</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "1️⃣ <b>In Private Messages (PM):</b>\n"
    "Simply paste any article URL or YouTube link. The bot automatically scrapes the page, "
    "publishes a Telegraph Instant View link, and generates a Gemini AI summary.\n\n"
    "2️⃣ <b>In Telegram Groups:</b>\n"
    "• <code>/read &lt;URL&gt;</code> — Clean Instant View + AI TL;DR + PDF export button\n"
    "• <code>/summary &lt;URL&gt;</code> — Executive AI bullet-point breakdown\n\n"
    "3️⃣ <b>Inline Mode (Any Chat):</b>\n"
    f"Type <code>@{Config.BOT_USERNAME} https://example.com/article</code> in any chat input bar "
    "to share an instant summary card on the fly.\n\n"
    "4️⃣ <b>Clean PDF Export:</b>\n"
    "Tap <b>[📥 Export Clean PDF]</b> below any processed link to receive a printable A4 document."
)


@Client.on_message(filters.command("start"))
@force_subscribe
async def start_command_handler(client: Client, message: Message) -> None:
    user = message.from_user
    if user:
        await db.ensure_user(user.id, user.first_name or "User", user.username)

    caption = build_welcome_caption(user.first_name if user else "Reader")
    keyboard = build_start_keyboard(Config.BOT_USERNAME)

    await render(message, "start", caption, keyboard)


@Client.on_message(filters.command("help"))
@force_subscribe
async def help_command_handler(client: Client, message: Message) -> None:
    await render(
        message,
        "help",
        HELP_TEXT,
        InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back to Home", callback_data="nav_home")]]
        ),
    )


@Client.on_message(filters.command("myaccount"))
@force_subscribe
async def myaccount_command_handler(client: Client, message: Message) -> None:
    user = message.from_user
    if not user:
        return
    text, markup = await _render_account_view(user.id, user.first_name, user.username)
    await render(message, "account", text, markup)


async def _render_account_view(
    user_id: int, first_name: str, username: str | None
) -> tuple[str, InlineKeyboardMarkup]:
    doc = await db.ensure_user(user_id, first_name, username)
    is_premium = bool(doc.get("is_premium"))
    used_today = int(doc.get("daily_usage_count", 0))
    total_reads = int(doc.get("total_reads", 0))
    joined_dt = doc.get("joined_date")
    joined_str = (
        joined_dt.astimezone(timezone.utc).strftime("%d %b %Y")
        if hasattr(joined_dt, "astimezone")
        else "Active"
    )

    if is_premium:
        expiry = doc.get("premium_expiry")
        expiry_str = (
            expiry.astimezone(timezone.utc).strftime("%d %b %Y (%H:%M UTC)")
            if hasattr(expiry, "astimezone")
            else "Lifetime"
        )
        tier_line = "💎 <b>Premium Subscriber (Unlimited)</b>"
        quota_line = f"♾ <b>Daily Quota:</b> Unlimited ({used_today} used today)"
        expiry_line = f"⏳ <b>Valid Until:</b> <code>{expiry_str}</code>\n"
    else:
        remaining = max(0, Config.FREE_DAILY_LIMIT - used_today)
        tier_line = "🆓 <b>Free Tier Member</b>"
        quota_line = (
            f"📊 <b>Daily Usage:</b> <code>{used_today} / {Config.FREE_DAILY_LIMIT}</code> "
            f"({remaining} remaining today)"
        )
        expiry_line = ""

    text = (
        "👤 <b>My CleanReader Account</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
        f"🏷 <b>Name:</b> {html.escape(first_name or 'User')}\n"
        f"⭐ <b>Plan:</b> {tier_line}\n"
        f"{expiry_line}"
        f"{quota_line}\n"
        f"📚 <b>Total Lifetime Reads:</b> <code>{total_reads}</code>\n"
        f"📅 <b>Member Since:</b> <code>{joined_str}</code>"
    )

    buttons = []
    if not is_premium:
        buttons.append(
            [InlineKeyboardButton("💎 Upgrade to Premium", callback_data="nav_premium")]
        )
    buttons.append([InlineKeyboardButton("⬅️ Back to Home", callback_data="nav_home")])
    return text, InlineKeyboardMarkup(buttons)


@Client.on_callback_query(filters.regex(r"^fsub_refresh$"))
async def fsub_refresh_callback(client: Client, callback: CallbackQuery) -> None:
    user = callback.from_user
    if not user:
        return
    if not await is_user_subscribed(client, user.id):
        await callback.answer(
            "❌ You still haven't joined the channel! Join first, then tap Refresh.",
            show_alert=True,
        )
        return

    await callback.answer("✅ Subscription verified! Welcome aboard.", show_alert=False)
    await db.ensure_user(user.id, user.first_name or "User", user.username)
    caption = build_welcome_caption(user.first_name or "Reader")
    keyboard = build_start_keyboard(Config.BOT_USERNAME)
    await render(callback, "start", caption, keyboard)


@Client.on_callback_query(filters.regex(r"^nav_(home|help|account)$"))
@force_subscribe
async def navigation_callbacks(client: Client, callback: CallbackQuery) -> None:
    action = callback.data.split("_", 1)[1]
    user = callback.from_user
    msg = callback.message
    if not msg or not user:
        return

    if action == "home":
        screen = "start"
        content = build_welcome_caption(user.first_name or "Reader")
        markup = build_start_keyboard(Config.BOT_USERNAME)
    elif action == "help":
        screen = "help"
        content = HELP_TEXT
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back to Home", callback_data="nav_home")]]
        )
    else:
        screen = "account"
        content, markup = await _render_account_view(
            user.id, user.first_name or "User", user.username
        )

    await callback.answer()
    await render(callback, screen, content, markup)
      
