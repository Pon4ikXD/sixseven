# auth.py (исправленная версия)
import asyncio
import logging
import random
import os
from datetime import datetime
from playwright.async_api import async_playwright

from session_manager import save_session
from states import auth_states

logger = logging.getLogger(__name__)

# Константы
CODE_TIMEOUT_SECONDS = 600  # 10 минут


def get_random_user_agent():
    """Возвращает случайный user-agent"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ]
    return random.choice(user_agents)


async def wait_for_user_code(user_id: int, bot, status_msg) -> str:
    """Ожидание ввода кода 2FA от пользователя"""
    logger.info(f"⏳ Ожидание кода 2FA от пользователя {user_id}")

    auth_states[user_id] = {
        'waiting_for_code': True,
        'code_received': False,
        'code': None
    }

    minutes = CODE_TIMEOUT_SECONDS // 60
    await status_msg.edit_text(
        '🔐 Требуется двухфакторная аутентификация.\n'
        'Пожалуйста, введите код из письма, отправленного на вашу почту:\n\n'
        f'(У вас есть {minutes} минут)'
    )

    start_time = datetime.now()
    while (datetime.now() - start_time).seconds < CODE_TIMEOUT_SECONDS:
        if user_id in auth_states and auth_states[user_id].get('code_received'):
            code = auth_states[user_id].get('code')
            if user_id in auth_states:
                del auth_states[user_id]
            logger.info(f"✅ Код 2FA получен от пользователя {user_id}")
            return code
        await asyncio.sleep(0.5)

    if user_id in auth_states:
        del auth_states[user_id]
    logger.warning(f"⏰ Таймаут ожидания кода для пользователя {user_id}")
    raise TimeoutError("Время ожидания кода истекло")


async def authenticate_user(user_id: int, bot, status_msg) -> dict:
    """
    Новая версия авторизации под обновлённый дизайн Pulse
    """
    playwright = None
    browser = None
    context = None

    try:
        logger.info(f"🚀 Начинаем авторизацию для пользователя {user_id}")

        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--start-maximized']
        )

        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent=get_random_user_agent()
        )

        page = await context.new_page()

        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        logger.info(f"🌐 Переходим на страницу входа")

        # Переходим на страницу входа
        await page.goto('https://pulse.mirea.ru/login', wait_until='domcontentloaded')
        await asyncio.sleep(2)

        # НА СТРАНИЦЕ ТОЛЬКО КНОПКА "Войти"
        # Ждём кнопку "Войти" и кликаем
        login_button = await page.wait_for_selector('button:has-text("Войти"), a:has-text("Войти")', timeout=10000)
        await login_button.click()
        logger.info("🖱 Нажата кнопка 'Войти'")

        # Ждём перенаправления на SSO страницу
        await page.wait_for_url('**/realms/mirea/**', timeout=10000)
        logger.info("✅ Перенаправлены на SSO страницу")

        await asyncio.sleep(2)

        # На SSO странице ищем поля ввода
        try:
            # Поле email
            email_input = await page.wait_for_selector(
                'input[id="username"], input[name="username"], input[type="text"]', timeout=10000)
            await email_input.fill(os.getenv('UNIVERSITY_EMAIL'))
            logger.info("✅ Email введён")

            # Поле пароля
            password_input = await page.wait_for_selector('input[type="password"]', timeout=5000)
            await password_input.fill(os.getenv('UNIVERSITY_PASSWORD'))
            logger.info("✅ Пароль введён")

            # Кнопка "Войти" на SSO
            submit_btn = await page.wait_for_selector('button[type="submit"], input[type="submit"]', timeout=5000)
            await submit_btn.click()
            logger.info("🖱 Нажата кнопка входа на SSO")

            await asyncio.sleep(3)

        except Exception as e:
            logger.error(f"❌ Ошибка на SSO странице: {e}")
            raise

        # Проверяем 2FA
        try:
            logger.info("🔍 Проверяем наличие поля для 2FA...")
            code_input = await page.wait_for_selector(
                'input[type="text"][maxlength="6"], input[type="number"], input[name="code"]',
                timeout=5000
            )

            if code_input:
                logger.info(f"✅ Обнаружено поле для 2FA")
                code = await wait_for_user_code(user_id, bot, status_msg)
                logger.info(f"📦 Получен код: {code}")

                await code_input.fill(code)
                logger.info("✍️ Код введён")

                await asyncio.sleep(1)

                confirm_btn = await page.query_selector('button[type="submit"], button:has-text("Подтвердить")')
                if confirm_btn:
                    await confirm_btn.click()
                else:
                    await page.keyboard.press('Enter')

                await asyncio.sleep(3)

        except Exception as e:
            logger.info(f"ℹ️ 2FA не требуется: {e}")

        # Проверяем успешность
        await asyncio.sleep(3)
        current_url = page.url
        logger.info(f"📍 Текущий URL: {current_url}")

        # Если всё ещё на SSO — пробуем пропустить MAX
        if "sso.mirea.ru" in current_url:
            logger.info("✅ На странице SSO, ищем кнопку пропуска...")

            skip_selectors = [
                'button:has-text("Пропустить")',
                'button:has-text("Skip")',
                'button:has-text("Позже")',
                'button:has-text("later")',
                'a:has-text("Пропустить")'
            ]

            for selector in skip_selectors:
                try:
                    skip_btn = await page.wait_for_selector(selector, timeout=2000)
                    if skip_btn:
                        await skip_btn.click()
                        logger.info(f"✅ Нажата кнопка пропуска")
                        await asyncio.sleep(3)
                        break
                except:
                    continue

        # Переходим на страницу отметок
        await page.goto('https://pulse.mirea.ru/lessons/visiting-logs/selfapprove', wait_until='domcontentloaded')
        final_url = page.url
        logger.info(f"📍 Финальный URL: {final_url}")

        if 'login' in final_url:
            raise Exception("Не удалось войти в систему")

        logger.info(f"✅ Успешная авторизация для пользователя {user_id}")

        # Сохраняем сессию
        storage_state = await context.storage_state()
        session = {
            'storage_state': storage_state,
            'user_id': user_id,
            'timestamp': datetime.now().isoformat()
        }
        await save_session(session)

        return {'success': True}

    except Exception as e:
        logger.error(f"❌ Ошибка при авторизации: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}

    finally:
        logger.info("🧹 Закрываем ресурсы")
        if context:
            await context.close()
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()