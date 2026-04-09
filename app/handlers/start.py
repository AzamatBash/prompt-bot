from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from app.states import Purchase
from app.services import texts

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="🎁 Получить бесплатные промпты",
            callback_data="free_prompts",
        )],
        [types.InlineKeyboardButton(
            text="💳 Оплатить доступ",
            callback_data="buy_access",
        )],
    ])
    await message.answer(texts.get("start"), reply_markup=kb)


@router.message(Command("pay"))
async def cmd_pay(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Purchase.waiting_for_email)
    await message.answer(texts.get("enter_email"))
