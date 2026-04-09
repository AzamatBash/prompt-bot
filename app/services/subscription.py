import asyncio
import logging

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.bot import bot
from app.config import CHANNEL_ID
from app import db
from app.services import texts

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 3600


async def activate_subscription(user_id: int, payment_db_id: int, days: int) -> None:
    """Save subscription to DB and unban user so they can join the channel."""
    expires = await db.add_subscription(user_id, payment_db_id, days)
    logger.info("Subscription activated for user %s, expires %s", user_id, expires.isoformat())

    try:
        await bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=user_id, only_if_banned=True)
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.debug("User %s was not banned — nothing to unban", user_id)


async def revoke_subscription(user_id: int) -> None:
    """Ban user from the channel and deactivate subscription records.

    We keep the ban in place so the user cannot rejoin via invite link.
    activate_subscription() calls unban when the user pays again.
    """
    try:
        await bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        logger.info("User %s banned from channel %s", user_id, CHANNEL_ID)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.warning("Could not ban user %s: %s", user_id, e)

    await db.deactivate_subscriptions(user_id)


async def _notify_and_kick(user_id: int, chat_id: int) -> None:
    try:
        await bot.send_message(chat_id, texts.get("sub_expired"))
    except Exception:
        logger.debug("Could not notify user %s about expiry", user_id)

    await revoke_subscription(user_id)


async def _send_reminders() -> None:
    """Send reminders to users whose subscription expires soon."""
    users_3d = await db.get_subscriptions_for_reminder_3d()
    for uid in users_3d:
        try:
            await bot.send_message(uid, texts.get("reminder_3d"))
        except Exception:
            logger.debug("Could not send 3-day reminder to user %s", uid)
        await asyncio.sleep(0.04)

    if users_3d:
        logger.info("Sent 3-day reminders to %d users", len(users_3d))

    users_1d = await db.get_subscriptions_for_reminder_1d()
    for uid in users_1d:
        try:
            await bot.send_message(uid, texts.get("reminder_1d"))
        except Exception:
            logger.debug("Could not send 1-day reminder to user %s", uid)
        await asyncio.sleep(0.04)

    if users_1d:
        logger.info("Sent 1-day reminders to %d users", len(users_1d))


async def subscription_checker() -> None:
    """Background loop: send reminders and remove expired subscribers."""
    while True:
        try:
            await _send_reminders()

            expired = await db.get_expired_subscriptions()
            for user_id, chat_id in expired:
                await _notify_and_kick(user_id, chat_id)
            if expired:
                logger.info("Processed %d expired subscriptions", len(expired))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in subscription checker loop")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
