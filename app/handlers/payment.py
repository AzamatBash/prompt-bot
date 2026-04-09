import logging

from aiogram import Router, types
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from app.config import PLANS
from app.states import Purchase
from app.services.payment import create_payment
from app.services import texts

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(lambda c: c.data == "buy_access")
async def buy_access_handler(callback: CallbackQuery) -> None:
    rows = []
    for plan_id, plan in PLANS.items():
        rows.append([types.InlineKeyboardButton(
            text=f"{plan['label']} — {plan['amount']}₽",
            callback_data=f"plan:{plan_id}",
        )])

    kb = types.InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.answer(texts.get("choose_plan"), reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("plan:"))
async def plan_selected_handler(callback: CallbackQuery, state: FSMContext) -> None:
    plan_id = callback.data.split(":", 1)[1]
    plan = PLANS.get(plan_id)
    if plan is None:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return

    await state.update_data(plan_id=plan_id)
    await state.set_state(Purchase.waiting_for_email)

    await callback.message.answer(
        texts.get("enter_email", plan_label=plan["label"], plan_price=plan["amount"]),
    )
    await callback.answer()


@router.message(Purchase.waiting_for_email)
async def process_email(message: Message, state: FSMContext) -> None:
    email = message.text.strip()
    if "@" not in email or "." not in email:
        await message.answer(texts.get("invalid_email"))
        return

    data = await state.get_data()
    plan_id = data.get("plan_id", "1m")

    chat_id = message.from_user.id
    username = message.from_user.username

    try:
        pay_url = await create_payment(chat_id, email, username, plan_id)
        await message.answer(texts.get("payment_created", pay_url=pay_url))
    except Exception:
        logger.exception("Error creating payment")
        await message.answer(texts.get("payment_error"))
    finally:
        await state.clear()
