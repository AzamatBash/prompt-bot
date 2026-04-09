import logging
import uuid

from yookassa import Configuration, Payment

from app.config import (
    YOOKASSA_SHOP_ID,
    YOOKASSA_SECRET_KEY,
    PAYMENT_AMOUNT,
    CURRENCY,
    ITEM_NAME,
)
from app.bot import bot
from app import db

logger = logging.getLogger(__name__)

Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY


async def create_payment(chat_id: int, email: str, username: str | None) -> str:
    """Create a YooKassa payment, persist it in DB, and return the confirmation URL."""
    await db.upsert_user(chat_id, username, email)

    bot_info = await bot.get_me()
    description_suffix = f" (пользователь @{username})" if username else ""

    payment_data = {
        "amount": {"value": PAYMENT_AMOUNT, "currency": CURRENCY},
        "confirmation": {
            "type": "redirect",
            "return_url": f"https://t.me/{bot_info.username}",
        },
        "capture": True,
        "description": ITEM_NAME,
        "metadata": {"chat_id": str(chat_id)},
        "receipt": {
            "customer": {"email": email},
            "items": [
                {
                    "description": ITEM_NAME + description_suffix,
                    "quantity": "1.00",
                    "amount": {"value": PAYMENT_AMOUNT, "currency": CURRENCY},
                    "vat_code": 1,
                }
            ],
        },
    }

    payment = Payment.create(payment_data, uuid.uuid4())
    await db.create_payment_record(chat_id, payment.id, PAYMENT_AMOUNT, CURRENCY)

    logger.info("Payment %s created for user %s (email: %s)", payment.id, chat_id, email)
    return payment.confirmation.confirmation_url
