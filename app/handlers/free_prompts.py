from aiogram import Router, types
from aiogram.types import CallbackQuery

from app.bot import bot
from app.config import DATA_DIR
from app.services import texts
from app import db

router = Router()


@router.callback_query(lambda c: c.data == "free_prompts")
async def free_prompts_handler(callback: CallbackQuery) -> None:
    content = await db.get_free_prompts()

    if content:
        caption = content["caption"] or None
        ctype = content["type"]
        file_id = content["file_id"]

        if ctype == "photo":
            await callback.message.answer_photo(photo=file_id, caption=caption)
        elif ctype == "video":
            await callback.message.answer_video(video=file_id, caption=caption)
        elif ctype == "document":
            await callback.message.answer_document(document=file_id, caption=caption)
        else:
            await callback.message.answer(content["caption"] or texts.get("free_prompts"))
    else:
        file_path = DATA_DIR / "free_prompts.mp4"
        if file_path.exists():
            with open(file_path, "rb") as f:
                video = types.BufferedInputFile(f.read(), filename="free_prompts.mp4")
                await callback.message.answer_video(
                    video=video,
                    caption=texts.get("free_prompts"),
                )
        else:
            await callback.message.answer("📂 Контент пока не добавлен. Обратитесь к администратору.")

    await callback.answer()
