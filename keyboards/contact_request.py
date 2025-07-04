from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def contact_keyboard():
    kb = [
        [KeyboardButton(text="📱 Отправить контакт", request_contact=True)]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)
