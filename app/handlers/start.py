from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="📂 Получить бесплатные промпты",
            callback_data="free_prompts",
        )],
        [types.InlineKeyboardButton(
            text="💳 Оплатить доступ",
            callback_data="buy_access",
        )],
    ])
    await message.answer("👋 Привет! Выберите:", reply_markup=kb)
