"""
Custom Screen Images System (utils/images.py)
=============================================
Every screen of the bot can have its own picture.

Lookup order for a screen:
  1. Image set by an admin with /setimg <screen>   (stored in MongoDB, survives restarts)
  2. Env variable IMG_<SCREEN>   e.g. IMG_HELP=https://...
  3. The "default" image (admin-set, or env IMG_DEFAULT / START_IMG_URL)
  4. No image -> plain text message

To add a new screen: add one line to SCREENS, then call
    await render(target, "screen_key", text, markup)
wherever that screen is shown.
"""

import logging
import os
import re
from typing import Dict, Optional, Union

from pyrogram.errors import MessageNotModified
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from config import Config
from database import db

logger = logging.getLogger(__name__)

# screen key -> human label
SCREENS: Dict[str, str] = {
    "default": "Fallback for every screen without its own image",
    "start": "/start welcome screen",
    "help": "Help screen",
    "account": "My Account screen",
    "premium": "Premium Plans screen",
    "fsub": "Force-subscribe (join channel) screen",
}

CAPTION_LIMIT = 1024
_TAG_RE = re.compile(r"<[^>]+>")

_cache: Dict[str, str] = {}


async def load_images() -> None:
    """Load admin-set images from MongoDB into memory (call once at boot)."""
    global _cache
    try:
        _cache = await db.get_screen_images()
    except Exception as exc:
        logger.warning("Could not load screen images: %s", exc)
        _cache = {}


async def set_image(screen: str, image: str) -> None:
    await db.set_screen_image(screen, image)
    _cache[screen] = image


async def delete_image(screen: str) -> None:
    await db.delete_screen_image(screen)
    _cache.pop(screen, None)


def _env_image(screen: str) -> Optional[str]:
    if screen == "default":
        return os.getenv("IMG_DEFAULT") or Config.START_IMG_URL or None
    return os.getenv(f"IMG_{screen.upper()}") or None


def get_image(screen: str) -> Optional[str]:
    """Return URL / file_id to use for `screen`, or None."""
    return (
        _cache.get(screen)
        or _env_image(screen)
        or _cache.get("default")
        or _env_image("default")
    )


def describe(screen: str) -> str:
    """Where is the image of this screen coming from? (for /images)"""
    if _cache.get(screen):
        return "admin-set"
    if _env_image(screen):
        return "env"
    if screen != "default" and get_image(screen):
        return "default"
    return "none"


def _fits_caption(text: str) -> bool:
    return len(_TAG_RE.sub("", text)) <= CAPTION_LIMIT


async def render(
    target: Union[Message, CallbackQuery],
    screen: str,
    text: str,
    markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """
    Show `text` + `markup` with the screen's picture.

    - target is a Message  -> sends a new message (photo if an image exists)
    - target is a CallbackQuery -> edits the existing message in place; if the
      photo/text type has to change (Telegram can't convert text<->photo) the old
      message is deleted and a new one is sent.
    """
    image = get_image(screen) if _fits_caption(text) else None

    # ---------- new message ----------
    if isinstance(target, Message):
        if image:
            try:
                await target.reply_photo(photo=image, caption=text, reply_markup=markup)
                return
            except Exception as exc:
                logger.warning("Image for '%s' failed (%s) - using text.", screen, exc)
        await target.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
        return

    # ---------- edit existing (callback) ----------
    msg = target.message
    if not msg:
        return
    has_photo = bool(msg.photo)

    try:
        if image and has_photo:
            await msg.edit_media(
                InputMediaPhoto(media=image, caption=text), reply_markup=markup
            )
            return
        if not image and not has_photo:
            await msg.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
            return
    except MessageNotModified:
        return
    except Exception as exc:
        logger.warning("Edit for '%s' failed (%s) - resending.", screen, exc)

    # type changed (or edit failed): send fresh, then remove the old one
    sent = False
    if image:
        try:
            await msg.reply_photo(photo=image, caption=text, reply_markup=markup)
            sent = True
        except Exception as exc:
            logger.warning("Image for '%s' failed (%s) - using text.", screen, exc)
    if not sent:
        await msg.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
    try:
        await msg.delete()
    except Exception:
        pass
