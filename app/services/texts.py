"""
Editable bot texts with DB persistence and in-memory cache.

Every user-facing string the bot sends is stored here as a key.
Admins can change any text via the admin panel at runtime.
Templates support {named} placeholders — available vars are listed in `hint`.

Each text may optionally have attached media (photo / video / document).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app import db

if TYPE_CHECKING:
    from aiogram.types import Message

logger = logging.getLogger(__name__)

TEMPLATES: dict[str, dict] = {
    "start": {
        "label": "Приветствие",
        "default": "👋 Привет! Выберите:",
        "hint": "",
    },
    "free_prompts": {
        "label": "Подпись к видео",
        "default": "🎁 Бесплатные промпты",
        "hint": "",
    },
    "choose_plan": {
        "label": "Выбор тарифа",
        "default": "Выберите период подписки:",
        "hint": "",
    },
    "enter_email": {
        "label": "Запрос email",
        "default": "📧 Введите ваш email для получения чека:",
        "hint": "",
    },
    "invalid_email": {
        "label": "Ошибка email",
        "default": "❌ Пожалуйста, введите корректный email.",
        "hint": "",
    },
    "payment_error": {
        "label": "Ошибка платежа",
        "default": "Ошибка при создании платежа. Попробуйте позже.",
        "hint": "",
    },
    "payment_success": {
        "label": "Успешная оплата",
        "default": (
            "✅ Оплата прошла успешно!\n\n"
            "Добро пожаловать в сообщество 🎉\n"
            "Вот ваша ссылка для входа:\n{invite_link}\n\n"
            "Если возникнут вопросы — напишите."
        ),
        "hint": "{invite_link}",
    },
    "sub_expired": {
        "label": "Подписка истекла",
        "default": "⏰ Ваша подписка истекла. Для продления используйте /start",
        "hint": "",
    },
    "reminder_3d": {
        "label": "Напоминание (3 дня)",
        "default": (
            "⚠️ Ваша подписка истекает через 3 дня.\n"
            "Чтобы продлить доступ, используйте /start"
        ),
        "hint": "",
    },
    "reminder_1d": {
        "label": "Напоминание (1 день)",
        "default": (
            "🔔 Ваша подписка истекает завтра!\n"
            "Продлите доступ прямо сейчас — /start"
        ),
        "hint": "",
    },
    "payment_canceled": {
        "label": "Платёж отменён",
        "default": "❌ Оплата не прошла или была отменена.\nПопробуйте ещё раз — /pay",
        "hint": "",
    },
    "payment_refunded": {
        "label": "Возврат средств",
        "default": "💸 Произведён возврат средств. Доступ к каналу отозван.",
        "hint": "",
    },
}

# key -> {"text": str, "media_type": str|None, "media_file_id": str|None}
_cache: dict[str, dict] = {}

_MEDIA_LABELS = {"photo": "🖼 Фото", "video": "🎬 Видео", "document": "📎 Файл"}


class _SafeDict(dict):
    """Keeps unknown {placeholders} as-is instead of raising KeyError."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


async def load() -> None:
    """Load texts from DB into cache, inserting defaults for missing keys."""
    stored = await db.get_all_texts()
    _cache.clear()
    for key, meta in TEMPLATES.items():
        if key in stored:
            _cache[key] = {
                "text": stored[key]["value"],
                "media_type": stored[key].get("media_type"),
                "media_file_id": stored[key].get("media_file_id"),
            }
        else:
            _cache[key] = {
                "text": meta["default"],
                "media_type": None,
                "media_file_id": None,
            }
    logger.info("Loaded %d text templates", len(_cache))


def get(key: str, **kwargs) -> str:
    """Return text by key, formatted with kwargs. Unknown keys stay as-is."""
    entry = _cache.get(key)
    template = entry["text"] if entry else TEMPLATES.get(key, {}).get("default", key)
    if kwargs:
        return template.format_map(_SafeDict(**kwargs))
    return template


def get_media(key: str) -> dict | None:
    """Return media dict {"type": ..., "file_id": ...} or None."""
    entry = _cache.get(key)
    if entry and entry.get("media_type") and entry.get("media_file_id"):
        return {"type": entry["media_type"], "file_id": entry["media_file_id"]}
    return None


def media_label(key: str) -> str | None:
    """Human-readable label for attached media, or None."""
    media = get_media(key)
    if not media:
        return None
    return _MEDIA_LABELS.get(media["type"], media["type"])


async def send(target: Message | int, key: str, reply_markup=None, **kwargs):
    """Send a text (with optional media) to a Message or chat_id.

    If target is a Message, uses .answer_*().
    If target is an int (chat_id), uses bot.send_*().
    """
    from app.bot import bot

    text = get(key, **kwargs)
    media = get_media(key)

    if isinstance(target, int):
        if media:
            sender = {
                "photo": bot.send_photo,
                "video": bot.send_video,
                "document": bot.send_document,
            }.get(media["type"])
            if sender:
                kw_name = media["type"]
                return await sender(target, **{kw_name: media["file_id"]}, caption=text, reply_markup=reply_markup)
        return await bot.send_message(target, text, reply_markup=reply_markup)
    else:
        if media:
            method = {
                "photo": target.answer_photo,
                "video": target.answer_video,
                "document": target.answer_document,
            }.get(media["type"])
            if method:
                kw_name = media["type"]
                return await method(**{kw_name: media["file_id"]}, caption=text, reply_markup=reply_markup)
        return await target.answer(text, reply_markup=reply_markup)


async def set_text(key: str, value: str) -> None:
    """Update text in DB and cache (preserves media)."""
    await db.upsert_text(key, value)
    entry = _cache.get(key)
    if entry:
        entry["text"] = value
    else:
        _cache[key] = {"text": value, "media_type": None, "media_file_id": None}


async def set_text_with_media(
    key: str, value: str, media_type: str, media_file_id: str,
) -> None:
    """Update text + media in DB and cache."""
    await db.upsert_text_with_media(key, value, media_type, media_file_id)
    _cache[key] = {"text": value, "media_type": media_type, "media_file_id": media_file_id}


async def clear_media(key: str) -> None:
    """Remove media from a text template (keeps text)."""
    await db.clear_text_media(key)
    entry = _cache.get(key)
    if entry:
        entry["media_type"] = None
        entry["media_file_id"] = None


async def reset_text(key: str) -> None:
    """Reset text to default (remove from DB, update cache)."""
    await db.delete_text(key)
    meta = TEMPLATES.get(key)
    if meta:
        _cache[key] = {"text": meta["default"], "media_type": None, "media_file_id": None}
