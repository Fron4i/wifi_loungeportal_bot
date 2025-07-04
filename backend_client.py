# backend_client.py
import asyncio
import logging
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

PHP_BACKEND_URL = os.getenv("PHP_BACKEND_URL")
if not PHP_BACKEND_URL:
    logging.critical("ОШИБКА: PHP_BACKEND_URL не найден в .env файле!")
    # В реальном приложении здесь лучше возбуждать исключение, чтобы бот не запустился с неполной конфигурацией
    # raise ValueError("PHP_BACKEND_URL is not set in .env")

logger = logging.getLogger(__name__)

def normalize_phone_for_php(phone: str) -> str:
    """
    Нормализует номер телефона в соответствии с логикой PHP-скрипта:
    удаляет пробелы и начальный '+'
    """
    # Удаляем все нецифровые символы, кроме потенциального начального плюса
    cleaned_phone = ''.join(filter(lambda char: char.isdigit() or char == '+', phone))
    if cleaned_phone.startswith('+'):
        return cleaned_phone[1:]
    return cleaned_phone

async def update_user_on_backend(telegram_id: int, phone_number: str, is_subscribed: bool, user_name: int) -> tuple[bool, str]:
    """
    Отправляет данные пользователя (telegram_id, phone_number, is_subscribed) на PHP-бэкенд.
    Возвращает кортеж (True/False в зависимости от успеха, сообщение от бэкенда или об ошибке).
    """
    if not PHP_BACKEND_URL:
        msg = "URL бэкенда не настроен. Невозможно отправить данные."
        logger.error(msg)
        return False, msg

    normalized_phone = normalize_phone_for_php(phone_number)
    payload = {
        'telegram_id': str(telegram_id),
        'phone_number': normalized_phone, # PHP скрипт ожидает 'phone_number'
        'is_subscribed': 'true' if is_subscribed else 'false',
        'user_name': str(user_name)
    }
    logger.info(f"Отправка данных на бэкенд {PHP_BACKEND_URL}: {payload}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(PHP_BACKEND_URL, data=payload) as response:
                response_text = await response.text()
                logger.info(f"Ответ от бэкенда (status: {response.status}): {response_text.strip()}")
                
                if response.status == 200 and response_text.strip().upper() == "OK":
                    logger.info(f"Данные для telegram_id={telegram_id}, phone={normalized_phone} успешно обновлены на бэкенде.")
                    return True, "Данные успешно обновлены на сервере."
                elif response.status == 404 and "номер телефона не найден" in response_text.lower():
                    logger.warning(f"Бэкенд ответил: номер телефона {normalized_phone} (от telegram_id={telegram_id}) не найден. "
                                   "Это может означать, что captive portal еще не отправил исходные данные (MAC, IP, Phone).")
                    return False, "Номер телефона не найден в системе Wi-Fi. Возможно, вам нужно сначала подключиться к нашей сети Wi-Fi."
                else:
                    error_message = f"Ошибка от бэкенда: {response.status}, Ответ: {response_text.strip()}"
                    logger.error(error_message)
                    return False, f"Произошла ошибка при синхронизации с сервером Wi-Fi ({response.status})."
    except aiohttp.ClientConnectorError as e:
        logger.error(f"Ошибка соединения с бэкендом {PHP_BACKEND_URL}: {e}")
        return False, "Не удалось подключиться к серверу Wi-Fi. Пожалуйста, попробуйте позже."
    except Exception as e:
        logger.exception(f"Непредвиденная ошибка при отправке данных на бэкенд: {e}")
        return False, "Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже."