import asyncio
import logging

from aiohttp import web
from aiogram import types as aiogram_types
from aiogram.webhook.aiohttp_server import SimpleRequestHandler

from app.bot import bot, dp
from app.config import (
    TELEGRAM_WEBHOOK_URL,
    TELEGRAM_WEBHOOK_PATH,
    YOOKASSA_WEBHOOK_PATH,
    PORT,
)
from app.handlers import root_router
from app.webhooks.yookassa import yookassa_webhook_handler
from app import db
from app.services import texts
from app.services.subscription import subscription_checker

logger = logging.getLogger(__name__)

_checker_task: asyncio.Task | None = None


async def on_startup(app: web.Application) -> None:
    await db.init_db()
    await texts.load()

    await bot.set_my_commands([
        aiogram_types.BotCommand(command="start", description="🏠 Главное меню"),
        aiogram_types.BotCommand(command="pay", description="💳 Оплатить подписку"),
    ])

    logger.info("Setting Telegram webhook → %s", TELEGRAM_WEBHOOK_URL)
    await bot.set_webhook(TELEGRAM_WEBHOOK_URL)

    global _checker_task
    _checker_task = asyncio.create_task(subscription_checker())
    logger.info("Subscription checker started")


async def on_shutdown(app: web.Application) -> None:
    global _checker_task
    if _checker_task:
        _checker_task.cancel()
        _checker_task = None

    try:
        await bot.delete_webhook()
    except Exception:
        logger.exception("Error deleting webhook")

    await db.close_db()
    await bot.session.close()
    logger.info("Shutdown complete")


def create_app() -> web.Application:
    dp.include_router(root_router)

    app = web.Application()
    app.router.add_post(YOOKASSA_WEBHOOK_PATH, yookassa_webhook_handler)
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=TELEGRAM_WEBHOOK_PATH)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


def run() -> None:
    app = create_app()
    logger.info("Starting server on 0.0.0.0:%s", PORT)
    web.run_app(app, host="0.0.0.0", port=PORT)
