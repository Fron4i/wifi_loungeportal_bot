# handlers/start.py
import os
import logging
import asyncio
from dotenv import load_dotenv
from aiogram import Router, F, Bot
from aiogram.types import Message, ReplyKeyboardRemove, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from concurrent.futures import ThreadPoolExecutor


# Импортируем клавиатуры
from keyboards.contact_request import contact_keyboard
from keyboards.subscription import subscription_keyboard

# Импортируем клиент для бэкенда
from backend_client import update_user_on_backend
# from mikrotik_api_2 import add_bypass_by_telegram_id


# Загружаем переменные окружения
load_dotenv()
CHANNEL_ID_STR = os.getenv("CHANNEL_ID")
if not CHANNEL_ID_STR:
    raise ValueError("Переменная CHANNEL_ID не найдена в .env файле.")

try:
    CHANNEL_ID = int(CHANNEL_ID_STR)
except ValueError:
    CHANNEL_ID = CHANNEL_ID_STR # Оставляем как есть, если это @username

CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/arhipo_osipovka_eva")
CHANNEL_DISPLAY_NAME = os.getenv("CHANNEL_DISPLAY_NAME", "Архипо-Осиповка") # Вы изменили "Архипо-Осиповка Ева" на "Архипо-Осиповка"

logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=1)

# --- Состояния FSM ---
class AuthState(StatesGroup):
    waiting_for_contact = State()
    waiting_for_subscription_check = State()
    authorized_pending_wifi = State()

router = Router()

# --- Утилита send_or_edit_message (ИСПРАВЛЕНА) ---
async def send_or_edit_message(source: Message | CallbackQuery, text: str, reply_markup=None, parse_mode="HTML", show_alert_on_callback: str | None = None):
    """Утилита для отправки/редактирования сообщения и ответа на CallbackQuery."""
    if isinstance(source, CallbackQuery):
        # Пытаемся ответить на CallbackQuery перед редактированием.
        try:
            if show_alert_on_callback is not None:
                await source.answer(show_alert_on_callback, show_alert=True)
            else:
                await source.answer() # Просто убираем "часики"
        except TelegramBadRequest as e:
            logger.warning(f"Ошибка при ответе на CallbackQuery (id: {source.id}): {e}. "
                           f"Это может произойти, если callback-запрос устарел.")
        
        try:
            if source.message: # Убедимся, что сообщение существует
                await source.message.edit_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True
                )
            else:
                logger.warning(f"CallbackQuery (id: {source.id}) не имеет связанного сообщения (source.message is None). Невозможно отредактировать.")
        except TelegramBadRequest as e:
            msg_id = source.message.message_id if source.message else "N/A"
            if "message is not modified" in str(e).lower():
                logger.info(f"Сообщение (ID: {msg_id}) не было изменено, так как идентично текущему.")
            elif "message to edit not found" in str(e).lower() or "message can't be edited" in str(e).lower():
                logger.warning(f"Сообщение (ID: {msg_id}) для редактирования не найдено или не может быть отредактировано: {e}")
            elif "query is too old" in str(e).lower():
                 logger.warning(f"CallbackQuery (id: {source.id}, message_id: {msg_id}) слишком старый для редактирования сообщения: {e}")
            else:
                logger.warning(f"Не удалось отредактировать сообщение (ID: {msg_id}) по причине: {e}")
        except Exception as e:
            msg_id = source.message.message_id if source.message else "N/A"
            logger.exception(f"Непредвиденная ошибка при редактировании сообщения (ID: {msg_id}): {e}")

    elif isinstance(source, Message):
        await source.answer(text, reply_markup=reply_markup, parse_mode=parse_mode, disable_web_page_preview=True)


# --- Обработчик команды /start ---
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_name = message.from_user.first_name
    
    # Ваше форматирование текста
    welcome_text = (
        f"Привет, {user_name}! 👋\n\n"
        f"Добро пожаловать! Для доступа к бесплатному Wi-Fi необходимо:\n\n"
        f"1️⃣ Подтвердить свой номер телефона.\n"
        f"2️⃣ Подписаться на наш канал новостей и акций: <a href=\"{CHANNEL_LINK}\">{CHANNEL_DISPLAY_NAME}</a>\n\n"
        f"❗️<b>Нажимая кнопку <u>📱 Отправить контакт</u>, вы соглашаетесь с Политикой Конфиденциальности обработки данных.</b>❗️\n\n"
        f"Пожалуйста, нажмите кнопку ниже 👇"
    )
    
    await message.answer(
        welcome_text,
        reply_markup=contact_keyboard(),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await state.set_state(AuthState.waiting_for_contact)

# --- Обработчик получения контакта ---
@router.message(AuthState.waiting_for_contact, F.contact)
async def handle_contact(message: Message, state: FSMContext):
    contact = message.contact
    telegram_id = message.from_user.id
    phone_number = contact.phone_number

    raw_username = message.from_user.username  # str | None
    user_name = f"{raw_username}" if raw_username else None

    if message.from_user.id != contact.user_id:
        await message.answer("Пожалуйста, отправьте свой собственный контакт.", reply_markup=contact_keyboard())
        return

    await message.answer("Спасибо! Ваш контакт получен.", reply_markup=ReplyKeyboardRemove())
    
    await state.update_data(phone_number=phone_number, telegram_id=telegram_id,user_name=user_name)
    logger.info(f"Пользователь ({user_name}) {telegram_id} отправил контакт: {phone_number}")

    await message.answer(
        f"Отлично! Теперь, пожалуйста, подпишитесь на наш канал <a href=\"{CHANNEL_LINK}\">{CHANNEL_DISPLAY_NAME}</a> и нажмите кнопку '✅ Я подписался, проверить'.",
        reply_markup=subscription_keyboard(),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await state.set_state(AuthState.waiting_for_subscription_check)

# --- Логика проверки подписки и обновления на бэкенде ---
async def check_subscription_and_update_backend(user_id: int, bot: Bot, state: FSMContext, source: Message | CallbackQuery):
    user_data = await state.get_data()
    phone_number = user_data.get('phone_number')
    user_name    = user_data.get('user_name')

    if not phone_number:
        logger.error(f"Критическая ошибка: не найден phone_number в состоянии FSM для user_id {user_id} при проверке подписки.")
        error_msg = "Произошла внутренняя ошибка (не найден номер телефона). Пожалуйста, попробуйте начать сначала с /start."
        alert_msg_for_cb = error_msg if isinstance(source, CallbackQuery) else None
        await send_or_edit_message(source, error_msg, show_alert_on_callback=alert_msg_for_cb)
        await state.clear()
        return

    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        is_user_subscribed = member.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
        
        if is_user_subscribed:
            logger.info(f"Пользователь {user_id} (тел: {phone_number}) ПОДПИСАН на канал {CHANNEL_ID}. {user_name}")
            
            success, backend_message = await update_user_on_backend(
                telegram_id=user_id,
                phone_number=phone_number,
                is_subscribed=True,
                user_name=user_name
            )

            # loop = asyncio.get_event_loop()
            # await loop.run_in_executor(executor, add_bypass_by_telegram_id, user_id)

            restart_kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="/start")]],
                resize_keyboard=True,
                one_time_keyboard=True
            )

            if success:
                await state.set_state(AuthState.authorized_pending_wifi)
                final_text = (
                    "✅ Отлично, вы подписаны и ваши данные успешно переданы!\n\n"
                    "Доступ к Wi-Fi должен быть предоставлен автоматически при следующем подключении к нашей сети.\n\n"
                    "Если доступ не появится в течение нескольких минут после подключения к Wi-Fi, попробуйте переподключиться к сети или обратитесь к персоналу."
                )
                alert_msg_for_cb = "Вы подписаны! Данные отправлены." if isinstance(source, CallbackQuery) else None
                await send_or_edit_message(source, final_text, reply_markup=None, show_alert_on_callback=alert_msg_for_cb)
                await bot.send_message(
                    chat_id=user_id,
                    text="Перезапустить бота:",
                    reply_markup=restart_kb
                )
            else:
                error_text_backend = (
                    f"Вы подписаны на канал, спасибо! ✅\n\n"
                    f"⚠️ Однако, при передаче данных в систему Wi-Fi произошла проблема: <i>{backend_message}</i>\n\n"
                    f"Пожалуйста, убедитесь, что вы уже пробовали подключиться к нашей Wi-Fi сети (это важно для регистрации вашего устройства).\n"
                    f"Затем попробуйте нажать кнопку '✅ Я подписался, проверить' еще раз через пару минут.\n"
                    f"Если проблема не решится, обратитесь к администратору."
                )
                alert_msg_for_cb = f"Ошибка Wi-Fi: {backend_message}" if isinstance(source, CallbackQuery) else None
                await send_or_edit_message(source, error_text_backend, reply_markup=subscription_keyboard(), show_alert_on_callback=alert_msg_for_cb)
                await bot.send_message(
                    chat_id=user_id,
                    text="Перезапустить бота:",
                    reply_markup=restart_kb
                )
        
        else: # Пользователь НЕ ПОДПИСАН
            logger.info(f"Пользователь {user_id} (тел: {phone_number}) НЕ ПОДПИСАН на канал {CHANNEL_ID} (статус: {member.status}).")
            
            await update_user_on_backend(
                telegram_id=user_id,
                phone_number=phone_number,
                is_subscribed=False,
                user_name=user_name
            )
            
            not_subscribed_text = "⚠️ Вы еще не подписаны на наш канал. Пожалуйста, подпишитесь и затем нажмите кнопку '✅ Я подписался, проверить' еще раз."
            alert_msg_for_cb = "Вы не подписаны. Пожалуйста, подпишитесь." if isinstance(source, CallbackQuery) else None
            await send_or_edit_message(source, not_subscribed_text, reply_markup=subscription_keyboard(), show_alert_on_callback=alert_msg_for_cb)

    except TelegramBadRequest as e:
        logger.error(f"Ошибка Telegram API при проверке подписки для user_id {user_id} на {CHANNEL_ID}: {e}")
        api_error_text = (
            "К сожалению, не удалось проверить вашу подписку на канал.\n"
            "Это могло произойти, если бот не является администратором в новостном канале или указан неверный ID канала.\n\n"
            "Пожалуйста, сообщите об этой проблеме администратору."
        )
        alert_msg_for_cb = "Ошибка проверки подписки." if isinstance(source, CallbackQuery) else None
        await send_or_edit_message(source, api_error_text, reply_markup=subscription_keyboard(), show_alert_on_callback=alert_msg_for_cb)

    except Exception as e:
        logger.exception(f"Непредвиденная ошибка при проверке подписки/обновлении бэкенда для user_id {user_id}: {e}")
        unexpected_error_text = "Произошла непредвиденная ошибка при проверке подписки. Пожалуйста, попробуйте нажать кнопку проверки еще раз через некоторое время."
        alert_msg_for_cb = "Неизвестная ошибка. Попробуйте позже." if isinstance(source, CallbackQuery) else None
        await send_or_edit_message(source, unexpected_error_text, reply_markup=subscription_keyboard(), show_alert_on_callback=alert_msg_for_cb)


# --- Обработчик нажатия кнопки "Проверить подписку" ---
@router.callback_query(AuthState.waiting_for_subscription_check, F.data == "check_subscription")
async def callback_check_subscription(callback_query: CallbackQuery, bot: Bot, state: FSMContext):
    await check_subscription_and_update_backend(callback_query.from_user.id, bot, state, callback_query)


# --- Обработчик любых сообщений в ожидаемых состояниях (кроме тех, что обрабатываются выше) ---
@router.message(StateFilter(AuthState.waiting_for_contact, AuthState.waiting_for_subscription_check))
async def any_other_message_in_auth_flow(message: Message, state: FSMContext):
    current_state_str = await state.get_state()
    user_name = message.from_user.first_name

    # Игнорируем служебные сообщения
    if message.new_chat_members or message.left_chat_member or message.pinned_message or message.group_chat_created or message.supergroup_chat_created or message.channel_chat_created:
        return

    if current_state_str == AuthState.waiting_for_contact.state:
        await message.answer(
            f"{user_name}, пожалуйста, для продолжения нажмите кнопку '📱 Отправить контакт' ниже 👇",
            reply_markup=contact_keyboard()
        )
    elif current_state_str == AuthState.waiting_for_subscription_check.state:
        await message.answer(
            f"{user_name}, пожалуйста, подпишитесь на канал <a href=\"{CHANNEL_LINK}\">{CHANNEL_DISPLAY_NAME}</a> (если еще не сделали это) и затем нажмите кнопку '✅ Я подписался, проверить' под предыдущим сообщением.",
            reply_markup=subscription_keyboard(),
            parse_mode="HTML",
            disable_web_page_preview=True
        )

# --- Обработчик сообщений в состоянии "авторизован, ожидает активации Wi-Fi" ---
@router.message(AuthState.authorized_pending_wifi)
async def message_when_authorized(message: Message, state: FSMContext):
    # Игнорируем служебные сообщения
    if message.new_chat_members or message.left_chat_member or message.pinned_message or message.group_chat_created or message.supergroup_chat_created or message.channel_chat_created:
        return

    await message.answer(
        "Вы уже выполнили все необходимые шаги в боте! ✅\n\n"
        "Ваши данные переданы в систему Wi-Fi. Доступ должен активироваться автоматически при подключении к нашей Wi-Fi сети.\n"
        "Если вы хотите начать процесс заново (например, для другого номера телефона), используйте команду /start."
    )