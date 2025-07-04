# main.py
import asyncio
import os
import logging
import json # Добавлен импорт для json.dumps
import concurrent.futures
# import mikrotik_api_2
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage # Или другая FSM Storage



# Импортируем роутеры из handlers
from handlers import start # Убедитесь, что этот импорт корректен и файл handlers/start.py существует

# Настройка логирования
# 1) Подавляем INFO-логи aiogram.event
logging.getLogger('aiogram.event').setLevel(logging.WARNING)

# 2) Один форматтер для консоли и файлов
formatter = logging.Formatter(
    fmt='%(asctime)s - %(levelname)s - %(message)s\n- %(name)s - %(module)s:%(lineno)d\n',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 3) Консольный хэндлер
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(formatter)

# 4) Файловый хэндлер для основного лога
file_h = logging.FileHandler('bot.log', encoding='utf-8')
file_h.setLevel(logging.INFO)
file_h.setFormatter(formatter)

logging.root.handlers = [console, file_h]
logging.root.setLevel(logging.INFO)

# 5) Отдельный логгер bypass_cleanup
bypass_logger = logging.getLogger("bypass_cleanup")
bypass_logger.setLevel(logging.INFO)
bypass_logger.propagate = False
bypass_handler = logging.FileHandler("bypass_cleanup.log", encoding='utf-8')
bypass_handler.setFormatter(formatter)
bypass_logger.addHandler(bypass_handler)

# 6) Ваш модульный логгер
logger = logging.getLogger(__name__) # Получаем логгер для текущего модуля

async def main():
    load_dotenv() # Загружаем переменные окружения из .env файла

    BOT_TOKEN = os.getenv("BOT_TOKEN")
    PHP_BACKEND_URL = os.getenv("PHP_BACKEND_URL") # Используется в backend_client, но проверим его наличие здесь для общей диагностики

    # Критические проверки конфигурации
    if not BOT_TOKEN:
        logger.critical("КРИТИЧЕСКАЯ ОШИБКА: BOT_TOKEN не найден в .env файле! Запуск невозможен.")
        return
    if not PHP_BACKEND_URL:
        # Если PHP_BACKEND_URL критичен для работы, можно сделать это ошибкой
        logger.warning("ПРЕДУПРЕЖДЕНИЕ: PHP_BACKEND_URL не найден в .env файле. Взаимодействие с бэкендом может не работать.")
        # Если бот не может функционировать без этого, можно добавить:
        # logger.critical("КРИТИЧЕСКАЯ ОШИБКА: PHP_BACKEND_URL не найден. Запуск невозможен.")
        # return

    # Инициализация бота и диспетчера
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage() # Используем хранилище в памяти для FSM
    dp = Dispatcher(storage=storage)


    # Запускаем фоновую задачу очистки bypass ОЧИСТКА
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    # asyncio.create_task(periodic_clean_old_bypass(executor))

    # Регистрация роутеров (обработчиков команд и сообщений)
    # logger.info("Регистрация роутеров...")
    try:
        dp.include_routers(
            start.router
            # Если у вас есть другие файлы с роутерами в папке handlers, добавляйте их сюда:
            # from handlers import another_handler
            # dp.include_router(another_handler.router)
        )
        logger.info("Роутеры успешно зарегистрированы.")
    except ImportError as e:
        logger.exception(f"Ошибка импорта при регистрации роутеров: {e}. Убедитесь, что файл handlers/start.py существует и не содержит ошибок импорта.")
        return
    except Exception as e:
        logger.exception(f"Непредвиденная ошибка при регистрации роутеров: {e}")
        return


    # Удаление вебхука (если он был ранее установлен) перед запуском поллинга
    # drop_pending_updates=True сбрасывает обновления, полученные ботом, пока он был офлайн
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        # logger.info("Вебхук успешно удален, ожидающие обновления сброшены.")
    except Exception as e:
        logger.error(f"Ошибка при удалении вебхука (возможно, он не был установлен): {e}")

    # logger.info("Запуск бота в режиме поллинга с детальным логированием входящих апдейтов...")

    offset = None # Смещение для get_updates, чтобы получать только новые обновления
    # Определяем, какие типы обновлений интересуют наш диспетчер, чтобы не запрашивать лишнего у Telegram
    allowed_updates = dp.resolve_used_update_types()
    # logger.info(f"Диспетчер будет запрашивать и обрабатывать следующие типы апдейтов: {allowed_updates}")

    # Основной цикл получения и обработки обновлений
    while True:
        try:
            updates = await bot.get_updates(
                offset=offset,
                timeout=30, # Таймаут ожидания обновлений на стороне Telegram (в секундах)
                allowed_updates=allowed_updates
            )

            for update_obj in updates: # Имя переменной изменено на update_obj во избежание конфликта с модулем update
                # --- НАЧАЛО ДЕТАЛЬНОГО ЛОГИРОВАНИЯ КАЖДОГО АПДЕЙТА ---
                log_message_parts = [
                    f"ПОЛУЧЕН АПДЕЙТ (ID: {update_obj.update_id})",
                ]
                
                # Извлечение информации о пользователе и чате для лога
                user_info_str = "N/A"
                chat_info_str = "N/A"

                source_event = None
                if update_obj.message:
                    source_event = update_obj.message
                elif update_obj.edited_message:
                    source_event = update_obj.edited_message
                elif update_obj.channel_post:
                    source_event = update_obj.channel_post
                elif update_obj.edited_channel_post:
                    source_event = update_obj.edited_channel_post
                elif update_obj.callback_query:
                    source_event = update_obj.callback_query
                # Добавьте другие типы апдейтов по необходимости (inline_query, chosen_inline_result и т.д.)

                if hasattr(source_event, 'from_user') and source_event.from_user:
                    user_info_str = f"user_id: {source_event.from_user.id}, username: {source_event.from_user.username or 'None'}"
                
                chat_obj = None
                if hasattr(source_event, 'chat') and source_event.chat: # Для Message, ChannelPost
                    chat_obj = source_event.chat
                elif hasattr(source_event, 'message') and source_event.message and hasattr(source_event.message, 'chat') and source_event.message.chat: # для CallbackQuery
                    chat_obj = source_event.message.chat
                
                if chat_obj:
                    chat_info_str = f"chat_id: {chat_obj.id}, type: {chat_obj.type}"
                
                # log_message_parts.append(f"От: {user_info_str}")
                # log_message_parts.append(f"Чат: {chat_info_str}")

                # Безопасная сериализация содержимого апдейта в JSON для логирования
                try:
                    # Используем model_dump() для получения словаря из Pydantic модели
                    # mode='json' помогает с некоторыми внутренними преобразованиями типов Pydantic
                    update_dict = update_obj.model_dump(exclude_none=True, mode='json')
                    # Сериализуем словарь в JSON строку стандартной библиотекой json
                    # default=str используется для обработки типов, которые json не знает, как сериализовать
                    update_json_str = json.dumps(update_dict, indent=2, ensure_ascii=False, default=str)
                    # log_message_parts.append(f"Содержимое:\n{update_json_str}")
                except Exception as e_serialize:
                    logger.error(f"ВСЕГДА Ошибка сериализации содержимого апдейта {update_obj.update_id} в JSON: {e_serialize}")
                    # В случае ошибки, выводим хотя бы простое строковое представление
                    # log_message_parts.append(f"Содержимое (str, сериализация не удалась):\n{str(update_obj)}")
                
                # logger.info(" | ".join(log_message_parts))
                # --- КОНЕЦ ДЕТАЛЬНОГО ЛОГИРОВАНИЯ ---

                # Обновляем offset, чтобы в следующий раз получить только более новые обновления
                if update_obj.update_id:
                    offset = update_obj.update_id + 1
                
                # Передаем полученное обновление в диспетчер Aiogram для обработки зарегистрированными хендлерами
                try:
                    await dp.feed_update(bot=bot, update=update_obj)
                except Exception as e_dispatch:
                    # Эта ошибка означает, что что-то пошло не так уже внутри Aiogram при попытке найти или выполнить хендлер
                    logger.exception(f"Ошибка при обработке апдейта {update_obj.update_id} диспетчером: {e_dispatch}")

        except asyncio.CancelledError:
            logger.info("Поллинг отменен (asyncio.CancelledError). Завершение работы...")
            break # Выход из основного цикла while
        except Exception as e_poll:
            # Общие ошибки в цикле поллинга (например, сетевые проблемы при вызове get_updates)
            logger.exception(f"Критическая ошибка в основном цикле поллинга (get_updates): {e_poll}")
            logger.info("Пауза на 5 секунд перед повторной попыткой...")
            await asyncio.sleep(5) # Небольшая пауза перед тем, как пытаться снова

# async def periodic_clean_old_bypass(executor):
#     loop = asyncio.get_running_loop()
#     while True:
#         try:
#             # Запускаем функцию и логируем здесь
#             bypass_logger.info("Запускаем clean_old_bypass")
#             await loop.run_in_executor(executor, mikrotik_api_2.clean_old_bypass)
#             bypass_logger.info("clean_old_bypass завершена успешно")
#         except Exception as e:
#             bypass_logger.error(f"Ошибка при периодической очистке bypass: {e}")
#         await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную (KeyboardInterrupt).")
    except Exception as e_global:
        logger.exception(f"Непредвиденная критическая ошибка при запуске или во время работы бота: {e_global}")