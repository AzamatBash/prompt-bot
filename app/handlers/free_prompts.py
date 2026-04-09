import os

from aiogram import Router, types
from aiogram.types import CallbackQuery

from app.config import DATA_DIR

router = Router()


@router.callback_query(lambda c: c.data == "free_prompts")
async def free_prompts_handler(callback: CallbackQuery) -> None:
    file_path = DATA_DIR / "free_prompts.mp4"
    if file_path.exists():
        with open(file_path, "rb") as f:
            video = types.BufferedInputFile(f.read(), filename="free_prompts.mp4")
            await callback.message.answer_video(video=video, caption="🎁 Бесплатные промпты")
    else:
        await callback.message.answer("Файл не найден. Обратитесь к администратору.")
    await callback.answer()
