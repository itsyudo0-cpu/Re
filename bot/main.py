"""
CleanReader & Media Summarizer Bot - Entry Point (main.py)
==========================================================
Initializes the Pyrogram v2.x Client, Motor MongoDB indexes,
Telegraph Instant View account, and background tasks.
"""

import asyncio
import logging
import os
from aiohttp import web
from pyrogram import Client, idle
from pyrogram.enums import ParseMode
from config import Config
from database import db
from utils.extractor import extractor_service
from utils.images import load_images

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("CleanReaderBot")
logging.getLogger("pyrogram").setLevel(logging.WARNING)


async def start_health_server() -> web.AppRunner:
    """
    Tiny HTTP server so the bot can run as a Render *Web Service*.
    Render requires every Web Service to listen on $PORT; a polling bot
    alone opens no port, so the deploy is marked failed ("No open ports detected").
    Also gives an uptime monitor a URL to ping (/ or /health).
    """

    async def _ok(_request: web.Request) -> web.Response:
        return web.Response(text="CleanReader bot is running")

    app = web.Application()
    app.router.add_get("/", _ok)
    app.router.add_get("/health", _ok)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logger.info("Health server listening on port %s", port)
    return runner


async def main() -> None:
    Config.validate()

    # Open the HTTP port first so Render's port scan succeeds immediately
    health_runner = await start_health_server()

    # Initialize MongoDB indexes
    await db.initialize_indexes()

    # Load admin-set screen images (/setimg)
    await load_images()

    # Initialize Telegraph account for Instant View publishing
    await extractor_service.init_telegraph()

    app = Client(
        name="cleanreader_bot_session",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN,
        plugins=dict(root="plugins"),
        parse_mode=ParseMode.HTML,
        workers=16,
    )

    logger.info("Starting CleanReader & Media Summarizer Bot...")
    await app.start()

    me = await app.get_me()
    Config.BOT_USERNAME = me.username or Config.BOT_USERNAME
    logger.info(
        "Bot online as @%s (ID: %s) | FSUB: %s | Log Channel: %s",
        me.username,
        me.id,
        Config.FSUB_CHANNEL_ID,
        Config.LOG_CHANNEL_ID,
    )

    await idle()
    logger.info("Shutting down CleanReader Bot...")
    await app.stop()
    await health_runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped cleanly.")
        
