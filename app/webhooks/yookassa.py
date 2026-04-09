import logging

from aiohttp import web

from app.config import CHANNEL_INVITE
from app import db
from app.services.subscription import activate_subscription
from app.services import texts

logger = logging.getLogger(__name__)


async def yookassa_webhook_handler(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        logger.info("YooKassa webhook: %s", data)

        if data.get("event") == "payment.succeeded":
            payment_obj = data.get("object", {})
            yookassa_id = payment_obj.get("id")

            payment_row = await db.mark_payment_succeeded(yookassa_id)
            if payment_row is None:
                logger.warning("Payment %s not found or already processed", yookassa_id)
                return web.json_response({"status": "ok"})

            user_id = payment_row["user_id"]
            payment_db_id = payment_row["id"]
            plan_days = payment_row["plan_days"]

            await activate_subscription(user_id=user_id, payment_db_id=payment_db_id, days=plan_days)

            try:
                await texts.send(user_id, "payment_success", invite_link=CHANNEL_INVITE)
                logger.info("Invite sent to user %s (payment %s)", user_id, yookassa_id)
            except Exception:
                logger.exception("Failed to send invite to user %s", user_id)

        return web.json_response({"status": "ok"})
    except Exception:
        logger.exception("Error in YooKassa webhook")
        return web.json_response({"status": "error"}, status=500)
