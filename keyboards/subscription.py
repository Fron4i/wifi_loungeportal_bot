# keyboards/subscription.py
import os
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv

load_dotenv()
CHANNEL_USERNAME = os.getenv("CHANNEL_ID") # Получаем username канала из .env

# Проверяем, что переменная есть и содержит @
if not CHANNEL_USERNAME:
    raise ValueError("Переменная CHANNEL_ID не найдена в .env файле.")
if not CHANNEL_USERNAME.startswith('@'):
    CHANNEL_USERNAME = f'@{CHANNEL_USERNAME}'

# Формируем URL для подписки
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"

def subscription_keyboard() -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру с кнопками "Подписаться" и "Проверить подписку".
    """
    buttons = [
        [
            InlineKeyboardButton(text="➡️ Подписаться", url=CHANNEL_URL)
        ],
        [
            # callback_data будет содержать префикс и ID пользователя для проверки
            # Пока оставим просто префикс, ID добавим в хендлере если понадобится
            InlineKeyboardButton(text="✅ Я подписался, проверить", callback_data="check_subscription")
        ]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard

def already_subscribed_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура для уже подписанных пользователей (пример).
    Можно добавить кнопку для активации Wi-Fi.
    """
    buttons = [
        [
            InlineKeyboardButton(text="🚀 Активировать Wi-Fi", callback_data="activate_wifi")
        ],
        # Можно добавить кнопку повторной активации для других устройств
        [
            InlineKeyboardButton(text="🔄 Активировать на другом устройстве", callback_data="activate_other_device")
        ]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard