import logging

from aiohttp import web

from app.config import CHANNEL_INVITE
from app import db
from app.services.subscription import activate_subscription, revoke_subscription
from app.services import texts

logger = logging.getLogger(__name__)


async def yookassa_webhook_handler(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        logger.info("YooKassa webhook: %s", data)

        event = data.get("event")
        obj = data.get("object", {})

        if event == "payment.succeeded":
            await _handle_payment_succeeded(obj)

        elif event == "payment.canceled":
            await _handle_payment_canceled(obj)

        elif event == "refund.succeeded":
            await _handle_refund_succeeded(obj)

        return web.json_response({"status": "ok"})
    except Exception:
        logger.exception("Error in YooKassa webhook")
        return web.json_response({"status": "error"}, status=500)


async def _handle_payment_succeeded(obj: dict) -> None:
    yookassa_id = obj.get("id")
    metadata = obj.get("metadata", {})
    amount_obj = obj.get("amount", {})

    user_id = int(metadata.get("chat_id", 0))
    plan_days = int(metadata.get("plan_days", 30))
    amount = amount_obj.get("value", "0")
    currency = amount_obj.get("currency", "RUB")

    if not user_id:
        logger.error("No chat_id in metadata for payment %s", yookassa_id)
        return

    payment_row = await db.create_succeeded_payment(
        user_id=user_id,
        yookassa_id=yookassa_id,
        amount=amount,
        currency=currency,
        plan_days=plan_days,
    )
    if payment_row is None:
        logger.warning("Payment %s already processed (duplicate webhook)", yookassa_id)
        return

    await activate_subscription(
        user_id=user_id,
        payment_db_id=payment_row["id"],
        days=plan_days,
    )

    try:
        await texts.send(user_id, "payment_success", invite_link=CHANNEL_INVITE)
        logger.info("Invite sent to user %s (payment %s)", user_id, yookassa_id)
    except Exception:
        logger.exception("Failed to send invite to user %s", user_id)


async def _handle_payment_canceled(obj: dict) -> None:
    yookassa_id = obj.get("id")
    metadata = obj.get("metadata", {})
    user_id = int(metadata.get("chat_id", 0))

    if not user_id:
        logger.warning("No chat_id in metadata for canceled payment %s", yookassa_id)
        return

    logger.info("Payment %s canceled for user %s", yookassa_id, user_id)

    try:
        await texts.send(user_id, "payment_canceled")
    except Exception:
        logger.exception("Failed to notify user %s about cancellation", user_id)


async def _handle_refund_succeeded(obj: dict) -> None:
    payment_id = obj.get("payment_id")
    payment_row = await db.mark_payment_refunded(payment_id)
    if payment_row is None:
        logger.warning("Refund for payment %s not found or already processed", payment_id)
        return

    user_id = payment_row["user_id"]

    await revoke_subscription(user_id)

    try:
        await texts.send(user_id, "payment_refunded")
        logger.info("Refund notice sent to user %s (payment %s)", user_id, payment_id)
    except Exception:
        logger.exception("Failed to notify user %s about refund", user_id)
