import logging
import uuid

from yookassa import Configuration, Payment

from app.config import (
    YOOKASSA_SHOP_ID,
    YOOKASSA_SECRET_KEY,
    RECEIPT_EMAIL,
    PLANS,
    CURRENCY,
    ITEM_NAME,
)
from app.bot import bot
from app import db

logger = logging.getLogger(__name__)

Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY


async def create_payment(
    chat_id: int,
    username: str | None,
    plan_id: str,
) -> str:
    """Create a YooKassa payment, persist it in DB, and return the confirmation URL."""
    plan = PLANS[plan_id]
    amount = plan["amount"]
    days = plan["days"]
    label = plan["label"]

    await db.upsert_user(chat_id, username, None)

    bot_info = await bot.get_me()
    description_suffix = f" (пользователь @{username})" if username else ""

    payment_data = {
        "amount": {"value": amount, "currency": CURRENCY},
        "confirmation": {
            "type": "redirect",
            "return_url": f"https://t.me/{bot_info.username}",
        },
        "capture": True,
        "description": f"{ITEM_NAME} — {label}",
        "metadata": {"chat_id": str(chat_id), "plan_days": str(days)},
        "receipt": {
            "customer": {"email": RECEIPT_EMAIL},
            "items": [
                {
                    "description": f"{ITEM_NAME} ({label})" + description_suffix,
                    "quantity": "1.00",
                    "amount": {"value": amount, "currency": CURRENCY},
                    "vat_code": 1,
                }
            ],
        },
    }

    payment = Payment.create(payment_data, uuid.uuid4())
    await db.create_payment_record(chat_id, payment.id, amount, CURRENCY, days)

    logger.info("Payment %s created for user %s (%s)", payment.id, chat_id, label)
    return payment.confirmation.confirmation_url
