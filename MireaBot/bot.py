import os
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    CallbackQuery,
    WebAppInfo
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

from session_manager import load_session
from student_manager import student_manager
from auth_playwright import update_all_students
from pulse_api import mark_all_students

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://pon4ikxd.github.io/sixseven/")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment (.env)")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ============================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ============================================

stop_refresh_flag = False
current_refresh_task: Optional[asyncio.Task] = None


# ============================================
# КЛАВИАТУРЫ
# ============================================

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню - ТОЛЬКО ТЕКСТОВЫЕ КНОПКИ, БЕЗ INLINE КНОПОК"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📷 Сканировать QR")],  # Это текстовая кнопка, не inline
            [KeyboardButton(text="🔄 Обновить все сессии")],
            [KeyboardButton(text="📊 Статус сессий")],
            [KeyboardButton(text="⏹️ Остановить обновление")],
            [KeyboardButton(text="🔧 Отладка")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )


# ЭТОТ МЕТОД БОЛЬШЕ НЕ ИСПОЛЬЗУЕТСЯ - УДАЛЯЕМ INLINE КЛАВИАТУРУ
# def get_qr_keyboard() -> InlineKeyboardMarkup:
#     """Клавиатура для сканирования QR - УДАЛЕНО"""
#     pass


# ============================================
# ОБРАБОТЧИКИ КОМАНД
# ============================================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    students_count = len(student_manager.get_all_students())

    await message.answer(
        f"👋 **Pulse Scanner Bot**\n\n"
        f"📋 **Студентов в базе: {students_count}**\n\n"
        f"**Как пользоваться:**\n"
        f"1) Нажмите **📷 Сканировать QR** в меню снизу\n"
        f"2) Откроется WebApp с камерой\n"
        f"3) Разрешите доступ к камере\n"
        f"4) Наведите на QR-код пары\n"
        f"5) QR-код определится автоматически\n"
        f"6) Данные отправятся в бота\n\n"
        f"**Команды:**\n"
        f"• 📷 Сканировать QR - открыть камеру (кнопка снизу)\n"
        f"• 🔄 Обновить все сессии - переавторизация\n"
        f"• 📊 Статус сессий - проверить сессии\n"
        f"• ⏹️ Остановить обновление - прервать процесс\n"
        f"• 🔧 Отладка - информация для отладки",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )


@dp.message(Command("debug"))
async def cmd_debug(message: Message):
    """Отладочная информация"""
    students = student_manager.get_all_students()

    text = (
        f"🔧 **ОТЛАДКА**\n\n"
        f"**WebApp URL:**\n`{WEBAPP_URL}`\n\n"
        f"**Бот:** ✅ работает\n"
        f"**Студентов в базе:** {len(students)}\n\n"
        f"**Список студентов:**\n"
    )

    for student in students:
        status = await get_session_status(student['id'])
        text += f"• {student['name']}: {status['icon']}\n"

    await message.answer(text, parse_mode="Markdown")


@dp.message(lambda m: m.text == "📷 Сканировать QR")
async def scan_qr(message: Message):
    """Открыть сканер QR - через WebApp напрямую"""
    logger.info(f"User {message.from_user.id} opened QR scanner")

    # Формируем правильный URL
    webapp_url = WEBAPP_URL
    if not webapp_url.endswith('/'):
        webapp_url += '/'
    if not webapp_url.endswith('index.html'):
        webapp_url += 'index.html'

    logger.info(f"📱 Opening WebApp URL: {webapp_url}")

    # Отправляем сообщение с WebApp кнопкой
    # ЭТО ЕДИНСТВЕННАЯ INLINE КНОПКА, КОТОРАЯ БУДЕТ ПОКАЗАНА
    await message.answer(
        "📱 **Сканирование QR-кода**\n\n"
        "Нажмите кнопку ниже, чтобы открыть камеру.\n\n"
        "💡 **Инструкция:**\n"
        "1. Нажмите **📱 Открыть камеру**\n"
        "2. Разрешите доступ к камере\n"
        "3. Наведите на QR-код пары\n"
        "4. QR определится автоматически\n"
        "5. Данные отправятся в бота",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📱 Открыть камеру",
                web_app=WebAppInfo(url=webapp_url)
            )]
        ]),
        parse_mode="Markdown"
    )


# ============================================
# ОБРАБОТЧИК ДАННЫХ ИЗ WEBAPP
# ============================================

@dp.message(F.web_app_data)
async def handle_web_app_data(message: Message):
    """Обработка данных из WebApp"""
    user_id = message.from_user.id
    web_app_data = message.web_app_data

    # Подробное логирование
    logger.info("=" * 60)
    logger.info(f"📱 ПОЛУЧЕНЫ ДАННЫЕ ОТ WEBAPP!")
    logger.info(f"User ID: {user_id}")
    logger.info(f"User name: {message.from_user.full_name}")
    logger.info(f"Button text: {web_app_data.button_text}")
    logger.info(f"Data raw: {web_app_data.data}")
    logger.info(f"Data type: {type(web_app_data.data)}")
    logger.info(f"Data length: {len(web_app_data.data) if web_app_data.data else 0}")
    logger.info("=" * 60)

    # Отправляем подтверждение
    await message.answer(f"✅ Данные получены! Длина: {len(web_app_data.data)} символов")

    try:
        # Пробуем распарсить как JSON
        data = json.loads(web_app_data.data)
        logger.info(f"Parsed JSON: {json.dumps(data, indent=2, ensure_ascii=False)}")

        if isinstance(data, dict):
            data_type = data.get("type")

            if data_type == "qr_scanned":
                qr_code = data.get("code")

                if qr_code:
                    logger.info(f"✅ QR код получен: {qr_code[:100]}...")

                    status_msg = await message.answer(
                        "✅ **QR-код получен!**\n\n🔄 Отмечаю студентов...",
                        parse_mode="Markdown"
                    )

                    try:
                        # Отправляем отметку для всех студентов
                        result = await mark_all_students(qr_code)

                        # Формируем результат
                        result_text = (
                            f"📊 **РЕЗУЛЬТАТЫ ОТМЕТКИ**\n\n"
                            f"👥 **Всего студентов:** {result.get('total', 0)}\n"
                            f"✅ **Отмечены:** {result.get('success', 0)}\n"
                        )

                        if result.get('already_marked', 0) > 0:
                            result_text += f"🔄 **Уже отмечены:** {result['already_marked']}\n"

                        if result.get('need_reauth', 0) > 0:
                            result_text += f"⚠️ **Нужна переавторизация:** {result['need_reauth']}\n"
                            if result.get('need_reauth_list'):
                                names = [s['name'] for s in result['need_reauth_list']]
                                result_text += f"└ {', '.join(names)}\n"

                        await status_msg.edit_text(result_text, parse_mode="Markdown")

                    except Exception as e:
                        logger.error(f"Error marking students: {e}")
                        await status_msg.edit_text(f"❌ Ошибка при отметке: {str(e)}")

            elif data_type == "test":
                await message.answer(
                    f"✅ **Тест получен!**\n\n"
                    f"Сообщение: {data.get('message', 'пусто')}"
                )
            else:
                await message.answer(f"ℹ️ Получены данные типа: {data_type}")

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        await message.answer(
            f"❌ **Ошибка формата данных**\n\n"
            f"Текст: `{web_app_data.data[:200]}`\n"
            f"Ошибка: {e}"
        )
    except Exception as e:
        logger.error(f"Error processing webapp data: {e}")
        await message.answer(f"❌ **Ошибка обработки:** {str(e)}")


# ============================================
# ОСТАЛЬНЫЕ ОБРАБОТЧИКИ (без изменений)
# ============================================

@dp.message(lambda m: m.text == "📊 Статус сессий")
async def show_status(message: Message):
    """Показать статус всех сессий"""
    students = student_manager.get_all_students()
    if not students:
        await message.answer("📊 **Нет студентов в базе**")
        return

    text = "📊 **СТАТУС СЕССИЙ**\n\n"
    keyboard = []

    for student in students:
        status = await get_session_status(student["id"])
        text += f"{status['icon']} {student['name']}: {status['text']}\n"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{status['icon']} {student['name']}",
                callback_data=f"student_{student['id']}"
            )
        ])

    keyboard.append([InlineKeyboardButton(text="🔄 Обновить все", callback_data="refresh_all")])

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="Markdown"
    )


@dp.message(lambda m: m.text == "🔄 Обновить все сессии")
async def refresh_all_sessions(message: Message):
    """Обновить все сессии"""
    global stop_refresh_flag, current_refresh_task

    if current_refresh_task and not current_refresh_task.done():
        await message.answer("⚠️ Обновление уже запущено")
        return

    stop_refresh_flag = False
    students = student_manager.get_all_students()

    if not students:
        await message.answer("❌ Нет студентов в базе")
        return

    status_msg = await message.answer(f"🔄 Обновляю {len(students)} студентов...")

    async def progress(msg: str):
        if not stop_refresh_flag:
            try:
                await status_msg.edit_text(f"🔄 {msg}")
            except:
                pass

    async def run_update():
        global stop_refresh_flag
        results = await update_all_students(students, progress)

        if stop_refresh_flag:
            await status_msg.edit_text("⏹️ Обновление остановлено")
            return

        await status_msg.edit_text(
            f"✅ Обновление завершено!\n"
            f"✅ Успешно: {results['success']}\n"
            f"❌ Ошибок: {results['failed']}"
        )

    current_refresh_task = asyncio.create_task(run_update())


@dp.message(lambda m: m.text == "⏹️ Остановить обновление")
async def stop_refresh(message: Message):
    """Остановить обновление сессий"""
    global stop_refresh_flag, current_refresh_task

    if current_refresh_task and not current_refresh_task.done():
        stop_refresh_flag = True
        current_refresh_task.cancel()
        await message.answer("⏹️ Обновление остановлено")
    else:
        await message.answer("ℹ️ Нет активного обновления")


@dp.message(lambda m: m.text == "🔧 Отладка")
async def debug_button(message: Message):
    """Кнопка отладки"""
    await cmd_debug(message)


@dp.callback_query(lambda c: c.data.startswith("student_"))
async def process_student_callback(callback: CallbackQuery):
    student_id = int(callback.data.split("_")[1])
    student = student_manager.get_student(student_id)

    if not student:
        await callback.answer("Студент не найден")
        return

    status = await get_session_status(student_id)

    text = (
        f"👤 **{student['name']}**\n\n"
        f"📧 Логин: `{student['pulse_login']}`\n"
        f"📧 Почта: `{student['yandex_email']}`\n"
        f"📊 Статус: {status['icon']} {status['text']}\n"
    )

    if status.get('expires_in'):
        text += f"⏱️ Истекает через: {status['expires_in']}\n"

    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_status"))

    await callback.message.edit_text(
        text,
        reply_markup=keyboard.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_to_status")
async def back_to_status(callback: CallbackQuery):
    students = student_manager.get_all_students()

    text = "📊 **СТАТУС СЕССИЙ**\n\n"
    keyboard = []

    for student in students:
        status = await get_session_status(student["id"])
        text += f"{status['icon']} {student['name']}: {status['text']}\n"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{status['icon']} {student['name']}",
                callback_data=f"student_{student['id']}"
            )
        ])

    keyboard.append([InlineKeyboardButton(text="🔄 Обновить все", callback_data="refresh_all")])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "refresh_all")
async def refresh_all_callback(callback: CallbackQuery):
    await callback.answer("Запускаю обновление...")
    await callback.message.delete()

    students = student_manager.get_all_students()
    status_msg = await callback.message.answer(f"🔄 Обновляю {len(students)} студентов...")

    async def progress(msg: str):
        try:
            await status_msg.edit_text(f"🔄 {msg}")
        except:
            pass

    results = await update_all_students(students, progress)

    await status_msg.edit_text(
        f"✅ Обновление завершено!\n"
        f"✅ Успешно: {results['success']}\n"
        f"❌ Ошибок: {results['failed']}"
    )


# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

async def get_session_status(student_id: int) -> Dict[str, Any]:
    """Получить статус сессии студента"""
    session = await load_session(student_id)
    if not session:
        return {"icon": "❌", "text": "нет сессии"}

    timestamp = session.get("timestamp")
    if timestamp:
        try:
            created = datetime.fromisoformat(timestamp)
            age = (datetime.now() - created).total_seconds() / 3600
            if age < 2:
                remaining = 2 - age
                return {
                    "icon": "✅",
                    "text": f"активна",
                    "expires_in": f"{remaining:.1f}ч",
                    "created": created
                }
            else:
                return {
                    "icon": "⚠️",
                    "text": "истекла",
                    "created": created,
                    "age": f"{age:.1f}ч"
                }
        except:
            return {"icon": "❓", "text": "ошибка формата"}

    return {"icon": "❓", "text": "неизвестно"}


# ============================================
# ЗАПУСК БОТА
# ============================================

async def main():
    """Главная функция"""
    logger.info("=" * 60)
    logger.info("🚀 Бот запускается...")
    logger.info(f"📱 WebApp URL: {WEBAPP_URL}")
    logger.info(f"👥 Студентов в базе: {len(student_manager.get_all_students())}")
    logger.info("=" * 60)

    await bot.set_chat_menu_button(
        menu_button={"type": "default"}  # Убираем кастомную кнопку
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())