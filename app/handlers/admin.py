from __future__ import annotations

import asyncio
import math
import logging

from aiogram import Router, types
from aiogram.filters import Command, Filter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.config import ADMIN_IDS, CHANNEL_ID, CHANNEL_INVITE
from app.bot import bot
from app.states import AdminBroadcast, AdminEditText, AdminEditFreePrompts
from app import db
from app.services import texts

logger = logging.getLogger(__name__)
router = Router()

USERS_PER_PAGE = 8
PAYS_PER_PAGE = 10


# ── filter ─────────────────────────────────────────────

class IsAdmin(Filter):
    async def __call__(self, event: Message | CallbackQuery, **kwargs) -> bool:
        return event.from_user is not None and event.from_user.id in ADMIN_IDS


# ── helpers ────────────────────────────────────────────

def _back(text: str = "🔙 Главное меню", data: str = "adm") -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=text, callback_data=data)]


def _paginator(page: int, total_pages: int, prefix: str) -> list[InlineKeyboardButton]:
    btns: list[InlineKeyboardButton] = []
    if page > 0:
        btns.append(InlineKeyboardButton(text="◀️", callback_data=f"{prefix}:{page - 1}"))
    btns.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        btns.append(InlineKeyboardButton(text="▶️", callback_data=f"{prefix}:{page + 1}"))
    return btns


def _fmt_date(dt) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%d.%m.%y %H:%M")


def _user_label(rec) -> str:
    return f"@{rec['username']}" if rec["username"] else str(rec["user_id"])


# ── noop (page counter button) ─────────────────────────

@router.callback_query(lambda c: c.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


# ── main menu ──────────────────────────────────────────

def _main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:users:0")],
        [InlineKeyboardButton(text="💳 Платежи", callback_data="adm:pays:0")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:bc")],
        [InlineKeyboardButton(text="✏️ Тексты", callback_data="adm:texts")],
        [InlineKeyboardButton(text="🎁 Бесплатные промпты", callback_data="adm:fp")],
    ])


@router.message(Command("admin"), IsAdmin())
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🔐 Админ-панель", reply_markup=_main_kb())


@router.callback_query(IsAdmin(), lambda c: c.data == "adm")
async def cb_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("🔐 Админ-панель", reply_markup=_main_kb())
    await callback.answer()


# ── users list (paginated) ─────────────────────────────

@router.callback_query(IsAdmin(), lambda c: c.data and c.data.startswith("adm:users:"))
async def cb_users(callback: CallbackQuery) -> None:
    page = int(callback.data.rsplit(":", 1)[-1])
    total = await db.get_users_count()
    total_pages = max(1, math.ceil(total / USERS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))

    users = await db.get_users_page(page * USERS_PER_PAGE, USERS_PER_PAGE)

    rows: list[list[InlineKeyboardButton]] = []
    for u in users:
        icon = "✅" if u["has_active_sub"] else "❌"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {_user_label(u)}",
            callback_data=f"adm:user:{u['user_id']}",
        )])

    if total_pages > 1:
        rows.append(_paginator(page, total_pages, "adm:users"))
    rows.append(_back())

    await callback.message.edit_text(
        f"👥 Пользователи (всего: {total})",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


# ── user details ───────────────────────────────────────

async def _show_user(callback: CallbackQuery, user_id: int) -> None:
    info = await db.get_user_info(user_id)
    if info is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    label = _user_label(info)
    email = info["email"] or "—"
    if info["sub_expires"]:
        sub_line = f"✅ активна до {_fmt_date(info['sub_expires'])}"
    else:
        sub_line = "❌ нет активной подписки"

    text = (
        f"👤 {label}\n"
        f"ID: <code>{info['user_id']}</code>\n"
        f"Email: {email}\n"
        f"Подписка: {sub_line}\n"
        f"Платежей: {info['payment_count']}\n"
        f"Зарегистрирован: {_fmt_date(info['created_at'])}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Забанить в канале", callback_data=f"adm:ban:{user_id}")],
        [InlineKeyboardButton(text="➖ Кикнуть из канала", callback_data=f"adm:kick:{user_id}")],
        [InlineKeyboardButton(text="➕ Добавить в канал", callback_data=f"adm:add:{user_id}")],
        [InlineKeyboardButton(text="💳 Платежи", callback_data=f"adm:upay:{user_id}:0")],
        [InlineKeyboardButton(text="🔙 К списку", callback_data="adm:users:0")],
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(IsAdmin(), lambda c: c.data and c.data.startswith("adm:user:"))
async def cb_user_detail(callback: CallbackQuery) -> None:
    user_id = int(callback.data.rsplit(":", 1)[-1])
    await _show_user(callback, user_id)


# ── user actions: ban / kick / add ─────────────────────

@router.callback_query(IsAdmin(), lambda c: c.data and c.data.startswith("adm:ban:"))
async def cb_ban(callback: CallbackQuery) -> None:
    user_id = int(callback.data.rsplit(":", 1)[-1])
    try:
        await bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        await callback.answer("✅ Пользователь забанен в канале", show_alert=True)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        await callback.answer(f"Ошибка: {e.message}", show_alert=True)
        return
    await _show_user(callback, user_id)


@router.callback_query(IsAdmin(), lambda c: c.data and c.data.startswith("adm:kick:"))
async def cb_kick(callback: CallbackQuery) -> None:
    user_id = int(callback.data.rsplit(":", 1)[-1])
    try:
        await bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        await bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        await callback.answer("✅ Пользователь удалён из канала", show_alert=True)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        await callback.answer(f"Ошибка: {e.message}", show_alert=True)
        return
    await _show_user(callback, user_id)


@router.callback_query(IsAdmin(), lambda c: c.data and c.data.startswith("adm:add:"))
async def cb_add(callback: CallbackQuery) -> None:
    user_id = int(callback.data.rsplit(":", 1)[-1])
    try:
        await bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=user_id, only_if_banned=True)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass

    if CHANNEL_INVITE:
        try:
            await bot.send_message(
                user_id,
                f"🎉 Вам открыт доступ в канал!\nСсылка: {CHANNEL_INVITE}",
            )
            await callback.answer("✅ Разбанен + ссылка отправлена", show_alert=True)
        except Exception:
            await callback.answer("✅ Разбанен, но не удалось отправить ссылку", show_alert=True)
    else:
        await callback.answer("✅ Пользователь разбанен в канале", show_alert=True)

    await _show_user(callback, user_id)


# ── user payments ──────────────────────────────────────

@router.callback_query(IsAdmin(), lambda c: c.data and c.data.startswith("adm:upay:"))
async def cb_user_payments(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    user_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0

    total = await db.get_user_payments_count(user_id)
    total_pages = max(1, math.ceil(total / PAYS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))

    pays = await db.get_user_payments_page(user_id, page * PAYS_PER_PAGE, PAYS_PER_PAGE)
    info = await db.get_user_info(user_id)
    label = _user_label(info) if info else str(user_id)

    lines = [f"💳 Платежи {label} (всего: {total})\n"]
    for p in pays:
        icon = "✅" if p["status"] == "succeeded" else "⏳"
        lines.append(f"{icon} #{p['id']} | {p['amount']} {p['currency']} | {_fmt_date(p['paid_at'] or p['created_at'])}")

    if not pays:
        lines.append("Нет платежей")

    rows: list[list[InlineKeyboardButton]] = []
    if total_pages > 1:
        rows.append(_paginator(page, total_pages, f"adm:upay:{user_id}"))
    rows.append([InlineKeyboardButton(text="🔙 К пользователю", callback_data=f"adm:user:{user_id}")])

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


# ── all payments (paginated) ───────────────────────────

@router.callback_query(IsAdmin(), lambda c: c.data and c.data.startswith("adm:pays:"))
async def cb_payments(callback: CallbackQuery) -> None:
    page = int(callback.data.rsplit(":", 1)[-1])
    total = await db.get_payments_count()
    total_pages = max(1, math.ceil(total / PAYS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))

    pays = await db.get_payments_page(page * PAYS_PER_PAGE, PAYS_PER_PAGE)

    lines = [f"💳 Платежи (всего: {total})\n"]
    for p in pays:
        icon = "✅" if p["status"] == "succeeded" else "⏳"
        label = f"@{p['username']}" if p["username"] else str(p["user_id"])
        lines.append(
            f"{icon} #{p['id']} | {label} | {p['amount']} {p['currency']} | {_fmt_date(p['paid_at'] or p['created_at'])}"
        )

    if not pays:
        lines.append("Нет платежей")

    rows: list[list[InlineKeyboardButton]] = []
    if total_pages > 1:
        rows.append(_paginator(page, total_pages, "adm:pays"))
    rows.append(_back())

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


# ── broadcast ──────────────────────────────────────────

@router.callback_query(IsAdmin(), lambda c: c.data == "adm:bc")
async def cb_broadcast_menu(callback: CallbackQuery) -> None:
    total_users = await db.get_users_count()
    active = await db.get_active_subscribers_count()
    expired = await db.get_expired_subscribers_count()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📨 Все пользователи ({total_users})", callback_data="adm:bc:all")],
        [InlineKeyboardButton(text=f"💰 С активной подпиской ({active})", callback_data="adm:bc:paid")],
        [InlineKeyboardButton(text=f"⏰ С истёкшей подпиской ({expired})", callback_data="adm:bc:exp")],
        _back(),
    ])

    await callback.message.edit_text("📢 Рассылка\n\nВыберите аудиторию:", reply_markup=kb)
    await callback.answer()


_TARGET_LABELS = {
    "all": "всем пользователям",
    "paid": "пользователям с активной подпиской",
    "exp": "пользователям с истёкшей подпиской",
}


@router.callback_query(IsAdmin(), lambda c: c.data and c.data.startswith("adm:bc:"))
async def cb_broadcast_target(callback: CallbackQuery, state: FSMContext) -> None:
    target = callback.data.rsplit(":", 1)[-1]
    if target not in _TARGET_LABELS:
        await callback.answer()
        return

    await state.set_state(AdminBroadcast.waiting_for_message)
    await state.update_data(broadcast_target=target)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm")],
    ])
    await callback.message.edit_text(
        f"📢 Рассылка {_TARGET_LABELS[target]}\n\nОтправьте сообщение (текст, фото, видео — что угодно):",
        reply_markup=kb,
    )
    await callback.answer()


@router.message(AdminBroadcast.waiting_for_message, Command("cancel"), IsAdmin())
async def cancel_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Рассылка отменена.", reply_markup=_main_kb())


@router.message(AdminBroadcast.waiting_for_message, IsAdmin())
async def process_broadcast(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    target = data.get("broadcast_target", "all")
    await state.clear()

    if target == "paid":
        user_ids = await db.get_active_subscriber_ids()
    elif target == "exp":
        user_ids = await db.get_expired_subscriber_ids()
    else:
        user_ids = await db.get_all_user_ids()

    if not user_ids:
        await message.answer("Аудитория пуста — никому не отправлено.", reply_markup=_main_kb())
        return

    status_msg = await message.answer(f"📤 Рассылка... 0/{len(user_ids)}")

    sent, failed = 0, 0
    for i, uid in enumerate(user_ids, 1):
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
            sent += 1
        except Exception:
            failed += 1

        if i % 25 == 0:
            try:
                await status_msg.edit_text(f"📤 Рассылка... {i}/{len(user_ids)}")
            except TelegramBadRequest:
                pass
        await asyncio.sleep(0.04)

    await status_msg.edit_text(
        f"✅ Рассылка завершена\n\nОтправлено: {sent}\nОшибок: {failed}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_back()]),
    )


# ── texts management ──────────────────────────────────

@router.callback_query(IsAdmin(), lambda c: c.data == "adm:texts")
async def cb_texts_list(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    rows: list[list[InlineKeyboardButton]] = []
    for key, meta in texts.TEMPLATES.items():
        current = texts.get(key)
        is_custom = current != meta["default"]
        icon = "🔵" if is_custom else "⚪"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {meta['label']}",
            callback_data=f"adm:txt:{key}",
        )])
    rows.append(_back())

    await callback.message.edit_text(
        "✏️ Тексты бота\n\n🔵 — изменён  ⚪ — по умолчанию",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(IsAdmin(), lambda c: c.data and c.data.startswith("adm:txt:"))
async def cb_text_detail(callback: CallbackQuery) -> None:
    key = callback.data.split(":", 2)[2]
    meta = texts.TEMPLATES.get(key)
    if not meta:
        await callback.answer("Неизвестный ключ", show_alert=True)
        return

    current = texts.get(key)
    is_default = current == meta["default"]

    hint_line = f"\n\nПеременные: {meta['hint']}" if meta["hint"] else ""
    status = "⚪ по умолчанию" if is_default else "🔵 изменён"

    msg = (
        f"✏️ {meta['label']} ({status})\n"
        f"Ключ: <code>{key}</code>"
        f"{hint_line}\n\n"
        f"Текущий текст:\n<pre>{current}</pre>"
    )

    btns: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="✏️ Изменить", callback_data=f"adm:tedt:{key}")],
    ]
    if not is_default:
        btns.append([InlineKeyboardButton(text="🔄 Сбросить", callback_data=f"adm:trst:{key}")])
    btns.append([InlineKeyboardButton(text="🔙 К текстам", callback_data="adm:texts")])

    await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns), parse_mode="HTML")
    await callback.answer()


@router.callback_query(IsAdmin(), lambda c: c.data and c.data.startswith("adm:tedt:"))
async def cb_text_edit(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 2)[2]
    meta = texts.TEMPLATES.get(key)
    if not meta:
        await callback.answer("Неизвестный ключ", show_alert=True)
        return

    await state.set_state(AdminEditText.waiting_for_text)
    await state.update_data(text_key=key)

    hint_line = f"\n\nДоступные переменные: {meta['hint']}" if meta["hint"] else ""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"adm:txt:{key}")],
    ])
    await callback.message.edit_text(
        f"✏️ Редактирование: {meta['label']}{hint_line}\n\nОтправьте новый текст:",
        reply_markup=kb,
    )
    await callback.answer()


@router.message(AdminEditText.waiting_for_text, Command("cancel"), IsAdmin())
async def cancel_text_edit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Редактирование отменено.", reply_markup=_main_kb())


@router.message(AdminEditText.waiting_for_text, IsAdmin())
async def process_text_edit(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Отправьте текстовое сообщение.")
        return

    data = await state.get_data()
    key = data.get("text_key")
    await state.clear()

    if key not in texts.TEMPLATES:
        await message.answer("Ошибка: неизвестный ключ.", reply_markup=_main_kb())
        return

    await texts.set_text(key, message.text)
    meta = texts.TEMPLATES[key]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К текстам", callback_data="adm:texts")],
        _back(),
    ])
    await message.answer(f"✅ Текст «{meta['label']}» сохранён.", reply_markup=kb)


@router.callback_query(IsAdmin(), lambda c: c.data and c.data.startswith("adm:trst:"))
async def cb_text_reset(callback: CallbackQuery) -> None:
    key = callback.data.split(":", 2)[2]
    meta = texts.TEMPLATES.get(key)
    if not meta:
        await callback.answer("Неизвестный ключ", show_alert=True)
        return

    await texts.reset_text(key)
    await callback.answer(f"✅ «{meta['label']}» сброшен", show_alert=True)

    current = texts.get(key)
    msg = (
        f"✏️ {meta['label']} (⚪ по умолчанию)\n"
        f"Ключ: <code>{key}</code>\n\n"
        f"Текущий текст:\n<pre>{current}</pre>"
    )
    btns: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="✏️ Изменить", callback_data=f"adm:tedt:{key}")],
        [InlineKeyboardButton(text="🔙 К текстам", callback_data="adm:texts")],
    ]
    await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns), parse_mode="HTML")


# ── free prompts management ───────────────────────────

_TYPE_LABELS = {"text": "📝 Текст", "photo": "🖼 Фото", "video": "🎬 Видео", "document": "📎 Файл"}


@router.callback_query(IsAdmin(), lambda c: c.data == "adm:fp")
async def cb_free_prompts_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    content = await db.get_free_prompts()

    if content:
        label = _TYPE_LABELS.get(content["type"], content["type"])
        caption_preview = content["caption"][:150] if content["caption"] else "—"
        preview = f"{label}\nПодпись: {caption_preview}"
    else:
        preview = "📁 Файл data/free_prompts.mp4 (по умолчанию)"

    btns: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="adm:fp:edit")],
    ]
    if content:
        btns.append([InlineKeyboardButton(text="👁 Предпросмотр", callback_data="adm:fp:preview")])
        btns.append([InlineKeyboardButton(text="🗑 Сбросить", callback_data="adm:fp:reset")])
    btns.append(_back())

    await callback.message.edit_text(
        f"🎁 Бесплатные промпты\n\n{preview}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
    )
    await callback.answer()


@router.callback_query(IsAdmin(), lambda c: c.data == "adm:fp:edit")
async def cb_fp_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminEditFreePrompts.waiting_for_content)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:fp")],
    ])
    await callback.message.edit_text(
        "🎁 Отправьте новый контент для бесплатных промптов:\n\n"
        "• 🖼 Фото с подписью\n"
        "• 🎬 Видео с подписью\n"
        "• 📎 Документ с подписью\n"
        "• 📝 Текстовое сообщение",
        reply_markup=kb,
    )
    await callback.answer()


@router.message(AdminEditFreePrompts.waiting_for_content, Command("cancel"), IsAdmin())
async def cancel_fp_edit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Редактирование отменено.", reply_markup=_main_kb())


@router.message(AdminEditFreePrompts.waiting_for_content, IsAdmin())
async def process_fp_edit(message: Message, state: FSMContext) -> None:
    await state.clear()

    content_type = ""
    file_id = ""
    caption = ""

    if message.photo:
        content_type = "photo"
        file_id = message.photo[-1].file_id
        caption = message.caption or ""
    elif message.video:
        content_type = "video"
        file_id = message.video.file_id
        caption = message.caption or ""
    elif message.document:
        content_type = "document"
        file_id = message.document.file_id
        caption = message.caption or ""
    elif message.text:
        content_type = "text"
        caption = message.text
    else:
        await message.answer("❌ Неподдерживаемый тип. Отправьте текст, фото, видео или документ.")
        return

    await db.set_free_prompts(content_type, file_id, caption)

    label = _TYPE_LABELS.get(content_type, content_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К промптам", callback_data="adm:fp")],
        _back(),
    ])
    await message.answer(f"✅ Бесплатные промпты обновлены ({label})", reply_markup=kb)


@router.callback_query(IsAdmin(), lambda c: c.data == "adm:fp:preview")
async def cb_fp_preview(callback: CallbackQuery) -> None:
    content = await db.get_free_prompts()
    if not content:
        await callback.answer("Контент не задан", show_alert=True)
        return

    ctype = content["type"]
    file_id = content["file_id"]
    caption = content["caption"] or None

    if ctype == "photo":
        await callback.message.answer_photo(photo=file_id, caption=caption)
    elif ctype == "video":
        await callback.message.answer_video(video=file_id, caption=caption)
    elif ctype == "document":
        await callback.message.answer_document(document=file_id, caption=caption)
    else:
        await callback.message.answer(content["caption"] or "—")

    await callback.answer()


@router.callback_query(IsAdmin(), lambda c: c.data == "adm:fp:reset")
async def cb_fp_reset(callback: CallbackQuery) -> None:
    await db.clear_free_prompts()
    await callback.answer("✅ Сброшено на файл по умолчанию", show_alert=True)

    btns = [
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="adm:fp:edit")],
        _back(),
    ]
    await callback.message.edit_text(
        "🎁 Бесплатные промпты\n\n📁 Файл data/free_prompts.mp4 (по умолчанию)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns),
    )
