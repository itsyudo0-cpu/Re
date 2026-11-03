"""
Monetization, Dynamic UPI QR Generator & Admin Verification Flow (plugins/premium.py)
=====================================================================================
1. Displays Premium Plans (1 Month, 3 Months, Lifetime).
2. Generates a dynamic UPI QR Code + deep-link (`upi://pay?pa=...`) for the chosen plan.
3. Accepts Screenshot or 12-digit UTR / Transaction Reference ID from the user in PM.
4. Forwards payment proof to `Config.LOG_CHANNEL_ID` and `Config.ADMIN_IDS` with
   interactive `[Approve ✅]` and `[Reject ❌]` buttons.
5. Upon Admin approval, updates MongoDB `is_premium = True` with `premium_expiry`
   and notifies the user automatically.
"""

import html
import io
import logging
import secrets
from urllib.parse import quote
import qrcode
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from config import Config
from database import db
from utils.images import render

logger = logging.getLogger(__name__)


def _build_upi_uri(amount: int, plan_label: str, user_id: int) -> str:
    pa = quote(Config.UPI_ID)
    pn = quote(Config.UPI_PAYEE_NAME)
    tn = quote(f"CleanReader {plan_label} UID {user_id}")
    return f"upi://pay?pa={pa}&pn={pn}&am={amount}.00&cu=INR&tn={tn}"


def _generate_qr_png_bytes(upi_uri: str) -> bytes:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=3,
    )
    qr.add_data(upi_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


@Client.on_callback_query(filters.regex(r"^nav_premium$"))
async def show_premium_plans_callback(client: Client, callback: CallbackQuery) -> None:
    msg = callback.message
    if not msg:
        return

    c = Config.CURRENCY_SYMBOL
    p1 = Config.PREMIUM_PLANS["1m"]
    p3 = Config.PREMIUM_PLANS["3m"]
    pl = Config.PREMIUM_PLANS["lifetime"]

    text = (
        "💎 <b>CleanReader & Media Summarizer — Premium Plans</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Unlock the full power of distraction-free reading and AI synthesis:\n\n"
        "✅ <b>Unlimited Daily Articles & Telegraph Instant Views</b>\n"
        "✅ <b>Unlimited YouTube Transcripts & AI Summaries</b>\n"
        "✅ <b>Unlimited Printable A4 PDF Exports</b>\n"
        "✅ <b>Priority Gemini AI Processing Queue</b>\n\n"
        "💳 <b>Select a Subscription Plan Below:</b>\n"
        f"• <b>{p1['label']}:</b> <code>{c}{p1['amount']}</code> (30 Days)\n"
        f"• <b>{p3['label']}:</b> <code>{c}{p3['amount']}</code> (90 Days — Best Value)\n"
        f"• <b>{pl['label']}:</b> <code>{c}{pl['amount']}</code> (Lifetime Access)"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"⚡ 1 Month — {c}{p1['amount']}", callback_data="buy_plan_1m"
                ),
                InlineKeyboardButton(
                    f"🔥 3 Months — {c}{p3['amount']}", callback_data="buy_plan_3m"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"👑 Lifetime Pass — {c}{pl['amount']}",
                    callback_data="buy_plan_lifetime",
                )
            ],
            [InlineKeyboardButton("⬅️ Back to Home", callback_data="nav_home")],
        ]
    )

    await callback.answer()
    await render(callback, "premium", text, keyboard)


@Client.on_callback_query(filters.regex(r"^buy_plan_(1m|3m|lifetime)$"))
async def generate_upi_qr_callback(client: Client, callback: CallbackQuery) -> None:
    user = callback.from_user
    msg = callback.message
    if not user or not msg:
        return

    plan_key = callback.matches[0].group(1)
    plan = Config.PREMIUM_PLANS.get(plan_key)
    if not plan:
        await callback.answer("Invalid plan selected.", show_alert=True)
        return

    await db.ensure_user(user.id, user.first_name or "User", user.username)
    await db.set_pending_payment_plan(user.id, plan_key)

    upi_uri = _build_upi_uri(plan["amount"], plan["label"], user.id)
    qr_bytes = _generate_qr_png_bytes(upi_uri)
    qr_stream = io.BytesIO(qr_bytes)
    qr_stream.name = f"CleanReader_UPI_{plan_key}_{user.id}.png"

    c = Config.CURRENCY_SYMBOL
    caption = (
        f"🧾 <b>Upgrade to {html.escape(plan['label'])}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Amount Payable:</b> <code>{c}{plan['amount']}.00</code>\n"
        f"🏦 <b>UPI ID:</b> <code>{html.escape(Config.UPI_ID)}</code>\n"
        f"🏷 <b>Payee Name:</b> {html.escape(Config.UPI_PAYEE_NAME)}\n"
        f"⏳ <b>Validity:</b> {plan['days']} Days\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📲 <b>How to Complete Payment:</b>\n"
        "1️⃣ Scan the QR Code above using any UPI App (GPay, PhonePe, Paytm, BHIM).\n"
        "2️⃣ After payment, <b>send the 12-digit UTR / Transaction Reference ID</b> "
        "or <b>upload the payment screenshot</b> right here in this chat.\n\n"
        "<i>An admin will verify and activate your Premium status immediately!</i>"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "❌ Cancel Payment Request", callback_data="cancel_pending_pay"
                )
            ]
        ]
    )

    await callback.answer("Generating dynamic UPI QR code...", show_alert=False)
    await msg.reply_photo(
        photo=qr_stream,
        caption=caption,
        reply_markup=keyboard,
    )


@Client.on_callback_query(filters.regex(r"^cancel_pending_pay$"))
async def cancel_pending_payment_callback(
    client: Client, callback: CallbackQuery
) -> None:
    if callback.from_user:
        await db.set_pending_payment_plan(callback.from_user.id, None)
    await callback.answer("Payment request cancelled.", show_alert=False)
    if callback.message:
        await callback.message.delete()


@Client.on_message(filters.private & (filters.photo | filters.text), group=2)
async def handle_payment_proof_submission(client: Client, message: Message) -> None:
    """
    Captures payment screenshot (photo) or UTR reference text when the user
    has an active `pending_payment_plan` in MongoDB.
    """
    user = message.from_user
    if not user:
        return

    # Ignore commands or URLs (handled in group 0)
    if message.text and (
        message.text.startswith("/") or "http://" in message.text or "https://" in message.text
    ):
        return

    user_doc = await db.ensure_user(user.id, user.first_name or "User", user.username)
    plan_key = user_doc.get("pending_payment_plan")
    if not plan_key or plan_key not in Config.PREMIUM_PLANS:
        return

    plan = Config.PREMIUM_PLANS[plan_key]
    payment_id = secrets.token_hex(4)
    utr_text = (message.text or message.caption or "Screenshot Uploaded").strip()

    await db.create_payment_submission(
        payment_id=payment_id,
        user_id=user.id,
        plan_key=plan_key,
        amount=plan["amount"],
        days=plan["days"],
        utr_or_caption=utr_text,
    )
    await db.set_pending_payment_plan(user.id, None)

    admin_caption = (
        "💳 <b>#PAYMENT_VERIFICATION — Manual UPI Proof</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>User:</b> <a href='tg://user?id={user.id}'>{html.escape(user.first_name or 'User')}</a>\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
        f"🏷 <b>Username:</b> @{html.escape(user.username or 'None')}\n"
        f"📦 <b>Selected Plan:</b> {html.escape(plan['label'])} ({plan['days']} days)\n"
        f"💰 <b>Expected Amount:</b> <code>{Config.CURRENCY_SYMBOL}{plan['amount']}</code>\n"
        f"🔢 <b>UTR / Note:</b> <code>{html.escape(utr_text[:180])}</code>\n"
        f"🔖 <b>Payment Ref:</b> <code>#{payment_id}</code>"
    )

    admin_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Approve ✅",
                    callback_data=f"pay_approve_{payment_id}_{user.id}_{plan['days']}",
                ),
                InlineKeyboardButton(
                    "Reject ❌",
                    callback_data=f"pay_reject_{payment_id}_{user.id}",
                ),
            ]
        ]
    )

    # Forward proof to LOG_CHANNEL_ID (and fallback to ADMIN_IDS)
    targets = [Config.LOG_CHANNEL_ID] if Config.LOG_CHANNEL_ID else Config.ADMIN_IDS
    for target_chat in targets:
        try:
            if message.photo:
                await client.send_photo(
                    chat_id=target_chat,
                    photo=message.photo.file_id,
                    caption=admin_caption,
                    reply_markup=admin_keyboard,
                )
            else:
                await client.send_message(
                    chat_id=target_chat,
                    text=admin_caption,
                    reply_markup=admin_keyboard,
                )
        except Exception as exc:
            logger.error("Failed to send payment proof to %s: %s", target_chat, exc)

    await message.reply_text(
        "✅ <b>Payment Proof Submitted!</b>\n\n"
        f"🔖 <b>Reference ID:</b> <code>#{payment_id}</code>\n"
        f"📦 <b>Plan:</b> {html.escape(plan['label'])}\n\n"
        "Your screenshot/UTR has been forwarded to our administrators. "
        "Your account will be upgraded automatically as soon as it is verified!",
        quote=True,
    )


@Client.on_callback_query(
    filters.regex(r"^pay_(approve|reject)_([a-f0-9]+)_(\d+)(?:_(\d+))?$")
)
async def admin_payment_decision_callback(
    client: Client, callback: CallbackQuery
) -> None:
    admin = callback.from_user
    if not admin or admin.id not in Config.ADMIN_IDS:
        await callback.answer(
            "⛔ Access Denied: Only bot administrators can approve or reject payments.",
            show_alert=True,
        )
        return

    decision = callback.matches[0].group(1)
    payment_id = callback.matches[0].group(2)
    target_user_id = int(callback.matches[0].group(3))
    days = int(callback.matches[0].group(4) or "30")

    payment_doc = await db.resolve_payment_submission(
        payment_id=payment_id,
        status="approved" if decision == "approve" else "rejected",
        admin_id=admin.id,
    )

    if decision == "approve":
        new_expiry = await db.grant_premium(target_user_id, days)
        expiry_str = new_expiry.strftime("%d %b %Y (%H:%M UTC)")
        status_stamp = (
            f"\n\n✅ <b>APPROVED by Admin</b> (<code>{admin.id}</code>)\n"
            f"⏳ <b>Expires:</b> <code>{expiry_str}</code>"
        )
        try:
            await client.send_message(
                chat_id=target_user_id,
                text=(
                    "🎉 <b>Payment Approved — Welcome to CleanReader Premium!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔖 <b>Payment Ref:</b> <code>#{payment_id}</code>\n"
                    f"⭐ <b>Duration Added:</b> <code>{days} Days</code>\n"
                    f"⏳ <b>Valid Until:</b> <code>{expiry_str}</code>\n\n"
                    "You now have <b>unlimited</b> clean web reads, YouTube AI summaries, "
                    "and instant A4 PDF exports!"
                ),
            )
        except Exception as exc:
            logger.warning("Could not notify user %s: %s", target_user_id, exc)
        await callback.answer("✅ Payment approved & Premium activated!", show_alert=False)
    else:
        status_stamp = f"\n\n❌ <b>REJECTED by Admin</b> (<code>{admin.id}</code>)"
        try:
            await client.send_message(
                chat_id=target_user_id,
                text=(
                    "⚠️ <b>Payment Verification Unsuccessful</b>\n\n"
                    f"Your payment submission (Ref <code>#{payment_id}</code>) could not be verified. "
                    "Please double-check your 12-digit UTR / screenshot or contact Support."
                ),
            )
        except Exception as exc:
            logger.warning("Could not notify user %s: %s", target_user_id, exc)
        await callback.answer("❌ Payment rejected & user notified.", show_alert=False)

    if callback.message:
        orig_text = callback.message.text or callback.message.caption or ""
        updated = orig_text + status_stamp
        if callback.message.photo:
            await callback.message.edit_caption(updated, reply_markup=None)
        else:
            await callback.message.edit_text(updated, reply_markup=None)
  
