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

PLAN_ICONS = {"1m": "⭐", "3m": "🔥", "6m": "💎", "12m": "👑"}


def _plans_keyboard() -> types.InlineKeyboardMarkup:
    rows = []
    for plan_id, plan in PLANS.items():
        icon = PLAN_ICONS.get(plan_id, "")
        rows.append([types.InlineKeyboardButton(
            text=f"{icon} {plan['label']} — {plan['amount']}₽",
            callback_data=f"plan:{plan_id}",
        )])
    rows.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_start")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(lambda c: c.data == "back_start")
async def back_to_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎁 Получить бесплатные промпты", callback_data="free_prompts")],
        [types.InlineKeyboardButton(text="💳 Оплатить доступ", callback_data="buy_access")],
    ])
    await callback.message.edit_text(texts.get("start"), reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data == "buy_access")
async def buy_access_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Purchase.waiting_for_email)
    await callback.message.answer(texts.get("enter_email"))
    await callback.answer()


@router.message(Purchase.waiting_for_email)
async def process_email(message: Message, state: FSMContext) -> None:
    email = message.text.strip()
    if "@" not in email or "." not in email:
        await message.answer(texts.get("invalid_email"))
        return

    await state.update_data(email=email)
    await state.set_state(Purchase.choosing_plan)
    await message.answer(texts.get("choose_plan"), reply_markup=_plans_keyboard())


@router.callback_query(lambda c: c.data and c.data.startswith("plan:"))
async def plan_selected_handler(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    email = data.get("email")
    if not email:
        await callback.answer("⚠️ Сначала введите email — нажмите /pay", show_alert=True)
        return

    plan_id = callback.data.split(":", 1)[1]
    plan = PLANS.get(plan_id)
    if plan is None:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return

    chat_id = callback.from_user.id
    username = callback.from_user.username

    try:
        pay_url = await create_payment(chat_id, email, username, plan_id)

        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="💳 Перейти к оплате", url=pay_url)],
        ])
        icon = PLAN_ICONS.get(plan_id, "")
        await callback.message.edit_text(
            f"{icon} {plan['label']} — {plan['amount']}₽\n\n"
            "👇 Нажмите кнопку для перехода к оплате:",
            reply_markup=kb,
        )
    except Exception:
        logger.exception("Error creating payment")
        await callback.message.edit_text(texts.get("payment_error"))
    finally:
        await state.clear()

    await callback.answer()
