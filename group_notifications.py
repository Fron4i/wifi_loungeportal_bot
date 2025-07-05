"""group_notifications.py
Расширение текущего бота: работа в группах + HTTP-точка для уведомлений
---------------------------------------------------------------------
• Бот может работать в личке (как раньше) и в группах.
• В группе админ вызывает /auth <CODE> — привязка этой группы к точке Wi-Fi, /unauth — отключение, /status — показать код.
• PHP-скрипт captive-портала вместо отправки сообщения в Telegram дергает HTTP POST /wifi_auth с данными авторизации.
• Бот ищет группу по коду и публикует красивое сообщение (и пересылает контакт, если передан message_id).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional

from aiohttp import web
from aiogram import Router, F, Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import Message
from dotenv import load_dotenv
import re
import secrets, string

from backend_client import (
    register_token_on_backend,
    check_token_on_backend,
    token_by_chat_on_backend,
    list_tokens_on_backend,
    token_by_nas_on_backend,
)

__all__ = [
    "router",
    "init",
    "start_http_server",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Конфигурация через .env
# ---------------------------------------------------------------------------
load_dotenv()

# Конфигурация HTTP-сервера
HTTP_HOST = os.getenv("GROUP_HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("GROUP_HTTP_PORT", "8080"))

# Конфигурация хранилища привязок
#  - sqlite (по умолчанию, локальный файл)
#  - mysql  (использует те же переменные, что и PHP-backend: DB_HOST, DB_NAME, DB_USER, DB_PASS)
STORAGE = os.getenv("GROUP_MAP_STORAGE", "remote").lower()
DB_PATH = os.getenv("GROUP_MAP_DB", "group_auth.db")  # используется, если STORAGE == 'sqlite'

# Параметры MySQL берём из .env (совпадают с submit.php)
MYSQL_HOST = os.getenv("DB_HOST")
MYSQL_DB   = os.getenv("DB_NAME")
MYSQL_USER = os.getenv("DB_USER")
MYSQL_PASS = os.getenv("DB_PASS")

# Унифицированный плейсхолдер для параметров SQL
_PH = "%s" if STORAGE == "mysql" else "?"

# ---------------------------------------------------------------------------
# Глобальный бот (будет установлен функцией init)
# ---------------------------------------------------------------------------
_bot: Optional[Bot] = None

# --- Конфигурация master-группы ---
MASTER_GROUP_ID = int(os.getenv("MASTER_GROUP_ID", "0"))  # 0 = отключено

# --- Утилита генерации токена ---
def _generate_token(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def _insert_token(token: str):
    try:
        _exec_sql(f"INSERT INTO group_auth(code) VALUES ({_PH})", (token,))
    except sqlite3.IntegrityError:
        # старый вариант таблицы требовал chat_id NOT NULL -> вставим 0
        _exec_sql(f"INSERT INTO group_auth(code, chat_id) VALUES ({_PH}, 0)", (token,))


def init(bot: Bot) -> None:
    """Сохраняем ссылку на основной объект Bot для дальнейшего использования."""
    global _bot
    _bot = bot


# ---------------------------------------------------------------------------
# Инициализируем соединение с БД в зависимости от STORAGE
# ---------------------------------------------------------------------------
if STORAGE == "mysql":
    try:
        import pymysql

        _conn = pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASS,
            database=MYSQL_DB,
            charset="utf8mb4",
            autocommit=True,
        )
        with _conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS group_auth (
                    code VARCHAR(128) PRIMARY KEY,
                    chat_id BIGINT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )
        logger.info("Хранилище привязок: MySQL (%s/%s)", MYSQL_HOST, MYSQL_DB)
    except Exception as exc:
        logger.exception("Не удалось подключиться к MySQL, переключаемся на SQLite. Ошибка: %s", exc)
        STORAGE = "sqlite"

if STORAGE == "sqlite":
    _conn = sqlite3.connect(DB_PATH)
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS group_auth (
            code TEXT PRIMARY KEY,
            chat_id INTEGER NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    _conn.commit()
    logger.info("Хранилище привязок: SQLite (%s)", DB_PATH)


def _exec_sql(query: str, params: tuple = (), fetch: bool = False):
    """Универсальный исполнитель для SQLite и PyMySQL."""
    cur = _conn.cursor()
    try:
        cur.execute(query, params)
        if fetch:
            rows = cur.fetchall()
            return rows
    finally:
        cur.close()

    if STORAGE == "sqlite":
        _conn.commit()  # В sqlite автокоммита нет по умолчанию


def _set_mapping(code: str, chat_id: int) -> None:
    _exec_sql(
        f"REPLACE INTO group_auth (code, chat_id, created_at) VALUES ({_PH},{_PH},{_PH})",
        (code, chat_id, datetime.utcnow()),
    )
    logger.info("Привязка обновлена: %s → %s", code, chat_id)


def _get_chat_id(code: str) -> Optional[int]:
    rows = _exec_sql(f"SELECT chat_id FROM group_auth WHERE code={_PH}", (code,), fetch=True)
    return int(rows[0][0]) if rows else None


def _remove_mapping(code: str) -> None:
    _exec_sql(f"DELETE FROM group_auth WHERE code={_PH}", (code,))
    logger.info("Привязка удалена: %s", code)

# ---------------------------------------------------------------------------
# Telegram router (работает внутри существующего Dispatcher)
# ---------------------------------------------------------------------------
router = Router()


@router.message(F.text.regexp(r"^/auth"))
async def cmd_auth(message: Message):
    """Привязка /auth <CODE> через PHP-бэкенд (локальной БД больше нет)."""
    if message.chat.type not in {"group", "supergroup"}:
        return await message.reply("Эта команда работает только в группах.")

    m = re.match(r"^/auth(?:@\w+)?\s+(\S+)$", message.text or "")
    if not m:
        return await message.reply("Формат: /auth <CODE> (пример: /auth 112233)")

    code = m.group(1)

    assert _bot is not None
    bot_member = await _bot.get_chat_member(message.chat.id, _bot.id)
    if bot_member.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
        return await message.reply("Я должен быть администратором группы, чтобы обрабатывать команды.")

    user_member = await _bot.get_chat_member(message.chat.id, message.from_user.id)
    if user_member.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
        return await message.reply("⛔️ Только администратор может выполнять авторизацию.")

    # Проверяем токен на сервере
    data = await check_token_on_backend(code)
    if not data or not data.get("ok"):
        return await message.reply("❌ Неизвестный токен.")

    busy = data.get("busy", False)
    current_chat = int(data.get("chat_id") or 0)

    if (not busy) or current_chat == 0:
        ok = await register_token_on_backend(code, chat_id=message.chat.id)
        if ok:
            await message.reply(f"✔️ Токен <b>{code}</b> успешно привязан к этой группе.")
        else:
            await message.reply("⚠️ Не удалось связаться с сервером. Попробуйте позже.")
    elif current_chat == message.chat.id:
        await message.reply("ℹ️ Этот токен уже привязан к текущей группе.")
    else:
        await message.reply("🚫 Этот токен уже используется другой группой.")


@router.message(F.text == "/status")
async def cmd_status(message: Message):
    data = await token_by_chat_on_backend(message.chat.id)
    if data and data.get("ok") and data.get("token"):
        token_val = data["token"]
        await message.reply(f"Эта группа авторизована кодом <code>{token_val}</code>.", parse_mode="HTML")
    else:
        await message.reply("Группа ещё не авторизована. Используйте /auth <CODE>.")


@router.message(F.text == "/unauth")
async def cmd_unauth(message: Message):
    assert _bot is not None
    user_member = await _bot.get_chat_member(message.chat.id, message.from_user.id)
    if user_member.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
        return await message.reply("⛔️ Только администратор может разрывать привязку.")

    data = await token_by_chat_on_backend(message.chat.id)
    token = data.get("token") if data and data.get("ok") else None
    if not token:
        return await message.reply("Привязка уже отсутствует.")

    ok = await register_token_on_backend(token, chat_id=0)
    if ok:
        await message.reply("✅ Токен отвязан от этой группы.")
    else:
        await message.reply("Не удалось обновить сервер. Попробуйте позже.")

# ---------------------------------------------------------------------------
# HTTP handler от captive-портала
# ---------------------------------------------------------------------------
async def _send_notification(data: Dict[str, Any]):
    """Фактическая отправка уведомления в группу по code."""
    code = data.get("code")
    if not code:
        logger.warning("Получен запрос без поля 'code': %s", data)
        return

    chat_id = data.get("chat_id")
    if not chat_id and code:
        info = await check_token_on_backend(code)
        chat_id = int(info.get("chat_id")) if info else None

    if not chat_id or int(chat_id) == 0:
        logger.warning("Неизвестный code=%s; уведомление пропущено.", code)
        return

    user_name = data.get("user_name") or "нет username"

    text = (
        "<i><b>Новая авторизация Wi-Fi</b></i>\n"
        f"<b>User_name:</b> {user_name}\n"
        f"<b>TG-ID:</b> {data.get('telegram_id','?')}\n"
        f"<b>TEL:</b> +{data.get('phone_number','?')}\n"
        f"<b>IP:</b> {data.get('ip','?')}\n"
        f"<b>MAC:</b> <code>{data.get('mac','?')}</code>"
    )

    # Пересылаем контакт (если есть)
    assert _bot is not None
    try:
        contact_chat = data.get("contact_chat_id")
        contact_msg = data.get("contact_message_id")
        if contact_chat and contact_msg:
            await _bot.forward_message(chat_id, int(contact_chat), int(contact_msg))
    except Exception:
        logger.exception("Не удалось переслать контактное сообщение (не критично).")

    await _bot.send_message(chat_id, text, disable_web_page_preview=True)


_routes = web.RouteTableDef()


@_routes.post("/wifi_auth")
async def wifi_auth(request: web.Request):
    """Endpoint, который вызывается из submit.php."""
    try:
        if request.content_type == "application/json":
            payload = await request.json()
        else:
            post_data = await request.post()
            payload = dict(post_data)
        logger.info("Получено уведомление: %s", payload)
        asyncio.create_task(_send_notification(payload))
        return web.Response(text="OK")
    except Exception as exc:
        logger.exception("Ошибка обработки уведомления: %s", exc)
        return web.Response(text="ERROR", status=500)

# ---------------------------------------------------------------------------
# HTTP-server launcher (вызывается из main.py)
# ---------------------------------------------------------------------------
async def start_http_server(host: str = HTTP_HOST, port: int = HTTP_PORT):
    app = web.Application()
    app.add_routes(_routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("HTTP-сервер для уведомлений запущен на %s:%s", host, port)

@router.message(F.text.regexp(r"^/gentoken"))
async def cmd_generate_token(message: Message):
    """/gentoken <nas_ip> [len]. Доступ только master-группе."""
    if MASTER_GROUP_ID == 0 or message.chat.id != MASTER_GROUP_ID:
        return

    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply("Формат: /gentoken <nas_ip> [длина]")

    nas_ip = parts[1]
    length = 32
    if len(parts) > 2 and parts[2].isdigit():
        length = max(8, min(int(parts[2]), 128))

    # проверяем, существует ли уже токен для этого nas_ip
    existing = await token_by_nas_on_backend(nas_ip)
    if existing and existing.get("token"):
        token = existing["token"]
        await message.reply(
            f"<b>Уже существует токен для {nas_ip}:</b> <code>{token}</code>\n"
            "Передайте его админу нужной группы, он привяжет командой /auth TOKEN",
            parse_mode="HTML")
        return

    # генерируем новый токен
    token = _generate_token(length)

    from backend_client import register_token_on_backend
    ok = await register_token_on_backend(token, chat_id=0, nas_ip=nas_ip)
    if ok:
        await message.reply(
            f"<b>Сгенерирован токен:</b> <code>{token}</code>\nПередайте его админу нужной группы, он привяжет командой /auth TOKEN",
            parse_mode="HTML")
    else:
        await message.reply("Не удалось зарегистрировать токен на сервере", parse_mode="HTML")


@router.message(F.text == "/tokens")
async def cmd_list_tokens(message: Message):
    """Получает полный список токенов из PHP-бэкенда."""
    if MASTER_GROUP_ID == 0 or message.chat.id != MASTER_GROUP_ID:
        return

    tokens = await list_tokens_on_backend()
    if not tokens:
        return await message.reply("Список токенов пуст.")

    lines = []
    for item in tokens:
        code = item.get("token") or "?"
        chat = item.get("chat_id") or 0
        nas  = item.get("nas_ip") or "?"
        status = "🔓 свободен" if int(chat) == 0 else f"🔒 chat_id {chat}"
        lines.append(f"<code>{code}</code> ({nas}) — {status}")

    await message.reply("\n".join(lines), parse_mode="HTML")