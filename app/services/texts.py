"""
Editable bot texts with DB persistence and in-memory cache.

Every user-facing string the bot sends is stored here as a key.
Admins can change any text via the admin panel at runtime.
Templates support {named} placeholders — available vars are listed in `hint`.
"""
from __future__ import annotations

import logging
from app import db

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
}

_cache: dict[str, str] = {}


class _SafeDict(dict):
    """Keeps unknown {placeholders} as-is instead of raising KeyError."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


async def load() -> None:
    """Load texts from DB into cache, inserting defaults for missing keys."""
    stored = await db.get_all_texts()
    _cache.clear()
    for key, meta in TEMPLATES.items():
        _cache[key] = stored.get(key, meta["default"])
    logger.info("Loaded %d text templates", len(_cache))


def get(key: str, **kwargs) -> str:
    """Return text by key, formatted with kwargs. Unknown keys stay as-is."""
    template = _cache.get(key, TEMPLATES.get(key, {}).get("default", key))
    if kwargs:
        return template.format_map(_SafeDict(**kwargs))
    return template


async def set_text(key: str, value: str) -> None:
    """Update text in DB and cache."""
    await db.upsert_text(key, value)
    _cache[key] = value


async def reset_text(key: str) -> None:
    """Reset text to default (remove from DB, update cache)."""
    await db.delete_text(key)
    meta = TEMPLATES.get(key)
    if meta:
        _cache[key] = meta["default"]
