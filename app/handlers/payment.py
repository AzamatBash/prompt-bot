import logging

from aiogram import Router
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from app.states import Purchase
from app.services.payment import create_payment

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(lambda c: c.data == "buy_access")
async def buy_access_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer("Пожалуйста, введите ваш email для получения чека:")
    await state.set_state(Purchase.waiting_for_email)
    await callback.answer()


@router.message(Purchase.waiting_for_email)
async def process_email(message: Message, state: FSMContext) -> None:
    email = message.text.strip()
    if "@" not in email or "." not in email:
        await message.answer("Пожалуйста, введите корректный email.")
        return

    await state.update_data(email=email)
    chat_id = message.from_user.id
    username = message.from_user.username

    data = await state.get_data()
    customer_email = data["email"]

    try:
        pay_url = await create_payment(chat_id, customer_email, username)
        await message.answer(
            f"Платёж создан. Перейдите по ссылке для оплаты:\n{pay_url}\n\n"
            "После оплаты бот пришлёт ссылку на канал."
        )
    except Exception:
        logger.exception("Error creating payment")
        await message.answer("Ошибка при создании платежа. Попробуйте позже.")
    finally:
        await state.clear()
