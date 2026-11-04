"""
CleanReader & Media Summarizer Bot - Environment & Configuration Module
=======================================================================
Loads and validates all required environment variables for Pyrogram,
Motor (Async MongoDB), Google Gemini API, Force-Subscribe (FSUB),
Activity Logging Channel, and Manual UPI Monetization.
"""

import os
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()


def _parse_int_or_str(value: str) -> int | str:
    """Parse channel ID/username: returns int if numeric (e.g. -100...), else str (@username)."""
    value = value.strip()
    if not value:
        return 0
    if value.lstrip("-").isdigit():
        return int(value)
    return value


def _parse_admin_ids(raw: str) -> List[int]:
    """Parse space- or comma-separated list of Telegram numeric User IDs."""
    ids: List[int] = []
    for token in raw.replace(",", " ").split():
        if token.strip().isdigit():
            ids.append(int(token.strip()))
    return ids


class Config:
    # 1. Telegram MTProto & Bot Credentials
    API_ID: int = int(os.getenv("API_ID", "26944587"))
    API_HASH: str = os.getenv("API_HASH", "7261a455f2a6159b8a2fbfecd1a63004")
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "8923673880:AAHM3TBMv3Oomk7KjDBLzpS0yrUSStMez2s")
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "CleanReaderBot").lstrip("@")

    # 2. MongoDB Async Driver (Motor) Configuration
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb+srv://otxstudioofficial1_db_user:MEAH3IXpZFAxHHew@cluster0.n23pbwq.mongodb.net/?appName=Cluster0")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "cleanreader_bot_db")

    # 3. Google Gemini API Configuration
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6JLe0PIuK04UKeqgx4OmH9LewUlNjlFLqY6_aF8NrzRnw")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # 4. Admin & Access Control
    ADMIN_IDS: List[int] = _parse_admin_ids(os.getenv("ADMIN_IDS", "7955232487,8531489053"))

    # 5. Force Subscribe (FSUB) Channel Configuration
    # Accepts numeric ID (-100xxxxxxxxxx) or public username (@ChannelUsername)
    FSUB_CHANNEL_ID: int | str = _parse_int_or_str(
        os.getenv("FSUB_CHANNEL_ID", "-1003944063310")
    )
    FSUB_INVITE_LINK: str = os.getenv(
        "FSUB_INVITE_LINK", "https://t.me/noharabots"
    )

    # 6. Telegram Activity Log & Database Channel
    # Private channel where bot logs reads, summaries, PDF uploads, and payment proofs
    LOG_CHANNEL_ID: int = int(os.getenv("LOG_CHANNEL_ID", "-1003813081550"))

    # 7. UI & Branding Assets
    START_IMG_URL: str = os.getenv(
        "START_IMG_URL",
        "https://i.ibb.co/27HC0c9h/1000180064.png",
    )
    SUPPORT_CHAT_URL: str = os.getenv(
        "SUPPORT_CHAT_URL", "https://t.me/noharabots"
    )
    TELEGRAPH_SHORT_NAME: str = os.getenv("TELEGRAPH_SHORT_NAME", "@CleanReaderbot")
    TELEGRAPH_AUTHOR_NAME: str = os.getenv(
        "TELEGRAPH_AUTHOR_NAME", "@CleanReaderbot"
    )

    # 8. Monetization, Quotas & UPI Payment Configuration
    FREE_DAILY_LIMIT: int = int(os.getenv("FREE_DAILY_LIMIT", "5"))
    UPI_ID: str = os.getenv("UPI_ID", "vickynohara@fam")
    UPI_PAYEE_NAME: str = os.getenv("UPI_PAYEE_NAME", "CleanReader Pro")
    CURRENCY_SYMBOL: str = os.getenv("CURRENCY_SYMBOL", "₹")

    PREMIUM_PLANS: Dict[str, Dict[str, Any]] = {
        "1m": {
            "id": "1m",
            "label": "1 Month Pro",
            "days": 30,
            "amount": int(os.getenv("PLAN_1M_PRICE", "99")),
            "description": "Unlimited clean articles, YouTube AI summaries & instant PDF exports for 30 days.",
        },
        "3m": {
            "id": "3m",
            "label": "3 Months Pro",
            "days": 90,
            "amount": int(os.getenv("PLAN_3M_PRICE", "249")),
            "description": "Save 16% — Full unlimited access, priority Gemini summarization & group privileges for 90 days.",
        },
        "lifetime": {
            "id": "lifetime",
            "label": "Lifetime Pass",
            "days": 36500,  # 100 years
            "amount": int(os.getenv("PLAN_LIFETIME_PRICE", "999")),
            "description": "One-time payment — Permanent unlimited access to all current and future CleanReader features.",
        },
    }

    @classmethod
    def validate(cls) -> None:
        """Ensure critical environment variables are configured before boot."""
        missing = []
        if not cls.API_ID:
            missing.append("API_ID")
        if not cls.API_HASH:
            missing.append("API_HASH")
        if not cls.BOT_TOKEN:
            missing.append("BOT_TOKEN")
        if not cls.MONGO_URI:
            missing.append("MONGO_URI")
        if not cls.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Please copy .env.example to .env and fill in all required credentials."
            )
