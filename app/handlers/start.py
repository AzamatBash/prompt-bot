from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from app.services import texts

router = Router()


def _start_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎁 Получить бесплатные промпты", callback_data="free_prompts")],
        [types.InlineKeyboardButton(text="💳 Оплатить доступ", callback_data="buy_access")],
    ])


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await texts.send(message, "start", reply_markup=_start_keyboard())


@router.message(Command("pay"))
async def cmd_pay(message: Message, state: FSMContext) -> None:
    await state.clear()
    from app.handlers.payment import _plans_keyboard
    await texts.send(message, "choose_plan", reply_markup=_plans_keyboard())
