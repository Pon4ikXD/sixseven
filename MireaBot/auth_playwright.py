# auth_playwright.py
import asyncio
import logging
import re
from datetime import datetime
from playwright.async_api import async_playwright

from session_manager import save_session
from email_imap import find_letter_by_id_and_get_code

logger = logging.getLogger(__name__)


class PulseAutoAuth:
    """Автоматическая авторизация в Pulse с получением 2FA кода из почты"""

    def __init__(self, student_data: dict):
        self.student = student_data
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.letter_id = None  # Здесь будем хранить двухзначный идентификатор (#6A, #13, #CF)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        """Закрывает все ресурсы"""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("🧹 Ресурсы Playwright закрыты")

    async def get_letter_id_from_page(self) -> str | None:
        """
        Извлекает двухзначный идентификатор из текста на странице 2FA
        Формат: (#6A), (#13), (#CF) - всегда два символа после #
        """
        try:
            # Получаем весь текст страницы
            page_text = await self.page.text_content('body')
            logger.debug(f"📄 Текст страницы: {page_text[:200]}...")

            # Ищем паттерн (#XY) где X и Y могут быть буквами или цифрами
            patterns = [
                r'\(#([A-Za-z0-9]{2})\)',  # (#6A), (#13), (#CF)
                r'#([A-Za-z0-9]{2})',  # #6A, #13, #CF (без скобок)
            ]

            for pattern in patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    letter_id = f"#{match.group(1)}"
                    logger.info(f"🔍 Найден идентификатор на странице: {letter_id}")
                    return letter_id

            # Если не нашли по паттернам, ищем в конкретных элементах
            elements = await self.page.query_selector_all('p, div, span, label, strong')
            for element in elements:
                text = await element.text_content()
                if text and ('код' in text.lower() or 'code' in text.lower()):
                    match = re.search(r'\(#([A-Za-z0-9]{2})\)', text)
                    if match:
                        letter_id = f"#{match.group(1)}"
                        logger.info(f"🔍 Найден идентификатор в элементе: {letter_id}")
                        return letter_id

            logger.warning("⚠️ Не удалось найти идентификатор на странице")
            return None

        except Exception as e:
            logger.error(f"❌ Ошибка при поиске идентификатора: {e}")
            return None

    async def handle_max_page(self, student_id: int) -> bool:
        """
        Обрабатывает страницу MAX, нажимает кнопку "Пропустить"
        Возвращает True если успешно, иначе False
        """
        logger.info("✅ Обнаружена страница MAX, ищем кнопку пропуска...")

        # Делаем скриншот для отладки
        try:
            await self.page.screenshot(path=f"max_page_{student_id}.png")
            logger.info("📸 Скриншот MAX страницы сохранён")
        except:
            pass

        # Ждём полной загрузки страницы
        await self.page.wait_for_load_state('networkidle')

        # Точные селекторы на основе HTML
        max_button_selectors = [
            # Самый точный селектор - кнопка с текстом "Пропустить"
            'button:has-text("Пропустить")',

            # Селектор по классам из PatternFly
            '.pf-c-button.pf-m-link:has-text("Пропустить")',
            '.pf-c-button:has-text("Пропустить")',

            # По атрибутам
            'button[type="button"]:has-text("Пропустить")',

            # Запасные варианты
            'button:has-text("Skip")',
            'a:has-text("Пропустить")',
            'input[type="submit"][value="Пропустить"]',
        ]

        # Пробуем найти кнопку по селекторам
        for selector in max_button_selectors:
            try:
                # Ждём появления кнопки
                button = await self.page.wait_for_selector(selector, timeout=5000)

                if button and await button.is_visible():
                    button_text = await button.text_content() or "без текста"
                    logger.info(f"🔍 Найдена кнопка по селектору: {selector}")
                    logger.info(f"📌 Текст кнопки: '{button_text}'")

                    # Пробуем разные способы клика
                    try:
                        await button.click()
                        logger.info(f"✅ Клик по кнопке выполнен")
                        await asyncio.sleep(3)
                        return True
                    except:
                        try:
                            await button.click(force=True)
                            logger.info(f"✅ Принудительный клик выполнен")
                            await asyncio.sleep(3)
                            return True
                        except:
                            await self.page.evaluate('(element) => element.click()', button)
                            logger.info(f"✅ Клик через JavaScript выполнен")
                            await asyncio.sleep(3)
                            return True
            except Exception as e:
                logger.debug(f"❌ Селектор {selector} не сработал: {e}")
                continue

        # Если не нашли по селекторам, ищем через JavaScript
        logger.warning("⚠️ Не найдена кнопка по селекторам, пробуем найти через JS...")
        try:
            # Ищем кнопку с текстом "Пропустить" через JavaScript
            found = await self.page.evaluate('''
                () => {
                    // Ищем по тексту
                    const buttons = Array.from(document.querySelectorAll('button, a, .pf-c-button'));
                    const skipButton = buttons.find(btn => 
                        btn.textContent.trim() === 'Пропустить' ||
                        btn.textContent.includes('Пропустить') ||
                        btn.textContent.trim() === 'Skip' ||
                        btn.textContent.includes('Skip')
                    );

                    if (skipButton) {
                        console.log('Найдена кнопка:', skipButton.textContent);
                        skipButton.click();
                        return true;
                    }

                    // Если не нашли, ищем по showSkip в данных
                    if (window.kcContext && window.kcContext.showSkip) {
                        console.log('showSkip=true, но кнопка не найдена');
                    }

                    return false;
                }
            ''')

            if found:
                logger.info("✅ Нажата кнопка через JavaScript поиск")
                await asyncio.sleep(3)
                return True
        except Exception as e:
            logger.error(f"❌ Ошибка при JavaScript поиске: {e}")

        # Если ничего не помогло, пробуем прямой переход
        logger.warning("⚠️ Не удалось нажать кнопку, пробуем прямой переход...")
        try:
            await self.page.goto(
                'https://pulse.mirea.ru/lessons/visiting-logs/selfapprove',
                wait_until='domcontentloaded'
            )
            logger.info("✅ Выполнен прямой переход на страницу отметок")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка при прямом переходе: {e}")

        # Если всё failed, сохраняем отладочную информацию
        logger.error("❌ НЕ УДАЛОСЬ ОБРАБОТАТЬ MAX СТРАНИЦУ!")

        # Сохраняем HTML страницы для анализа
        try:
            html = await self.page.content()
            with open(f"max_page_{student_id}_error.html", "w", encoding='utf-8') as f:
                f.write(html[:10000])
            logger.info("📄 HTML страницы сохранён")
        except:
            pass

        return False

    async def authenticate(self, progress_callback=None) -> dict:
        """
        Выполняет полный цикл авторизации
        """
        student_id = self.student['id']
        student_name = self.student['name']

        logger.info(f"🚀 Начинаем авторизацию для {student_name}")

        if progress_callback:
            await progress_callback("🔄 Запуск браузера...")

        try:
            # Запускаем Playwright
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                args=['--disable-blink-features=AutomationControlled',
                      '--no-sandbox',
                      '--start-maximized']
            )

            self.context = await self.browser.new_context(
                viewport={'width': 1280, 'height': 800}
            )

            # Добавляем скрипт для обхода детекта автоматизации
            await self.context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            self.page = await self.context.new_page()

            # Переходим на страницу входа Pulse
            if progress_callback:
                await progress_callback("🌐 Открытие страницы Pulse...")

            await self.page.goto('https://pulse.mirea.ru/login',
                                 wait_until='domcontentloaded')
            await asyncio.sleep(2)

            # ШАГ 1: Нажимаем кнопку "Войти" на главной странице Pulse
            if progress_callback:
                await progress_callback("🔑 Нажатие кнопки 'Войти'...")

            login_button = await self.page.wait_for_selector(
                'button:has-text("Войти"), a:has-text("Войти")',
                timeout=10000
            )
            await login_button.click()
            logger.info("🖱 Нажата кнопка 'Войти' на главной")

            # ШАГ 2: Ждём перенаправления на SSO страницу
            await self.page.wait_for_url('**/realms/mirea/**', timeout=10000)
            logger.info("✅ Перенаправлены на SSO страницу")
            await asyncio.sleep(2)

            # ШАГ 3: Вводим логин на SSO странице
            if progress_callback:
                await progress_callback("📧 Ввод логина...")

            email_input = await self.page.wait_for_selector(
                'input[id="username"], input[name="username"]',
                timeout=10000
            )
            await email_input.fill('')
            await email_input.type(self.student['pulse_login'], delay=50)
            logger.info(f"✅ Логин введён")

            # ШАГ 4: Вводим пароль
            if progress_callback:
                await progress_callback("🔐 Ввод пароля...")

            password_input = await self.page.wait_for_selector(
                'input[type="password"]',
                timeout=5000
            )
            await password_input.fill('')
            await password_input.type(self.student['pulse_password'], delay=50)
            logger.info(f"✅ Пароль введён")

            # ШАГ 5: Нажимаем кнопку входа на SSO
            submit_btn = await self.page.wait_for_selector(
                'button[type="submit"]',
                timeout=5000
            )
            await submit_btn.click()
            logger.info("🖱 Нажата кнопка входа на SSO")

            await asyncio.sleep(3)

            # ШАГ 6: Проверяем наличие 2FA
            try:
                if progress_callback:
                    await progress_callback("🔐 Проверка 2FA...")

                code_input = await self.page.wait_for_selector(
                    'input[type="text"][maxlength="6"], input[type="number"], input[name="code"], input[placeholder*="код"]',
                    timeout=5000
                )

                if code_input:
                    logger.info(f"✅ Обнаружено поле для 2FA")

                    # Получаем идентификатор письма со страницы
                    if progress_callback:
                        await progress_callback("🔍 Чтение идентификатора со страницы...")

                    self.letter_id = await self.get_letter_id_from_page()

                    if not self.letter_id:
                        raise Exception("Не удалось прочитать идентификатор письма со страницы")

                    logger.info(f"📨 Ищем письмо с идентификатором {self.letter_id}")

                    if progress_callback:
                        await progress_callback(f"📧 Поиск письма с ID {self.letter_id}...")

                    # Ищем в почте письмо с этим идентификатором
                    code = await find_letter_by_id_and_get_code(
                        self.student['yandex_email'],
                        self.student['yandex_app_password'],
                        letter_id=self.letter_id,
                        timeout=90
                    )

                    if not code:
                        raise Exception(f"Не удалось найти письмо с ID {self.letter_id}")

                    logger.info(f"📦 Получен 2FA код: {code}")

                    # Вводим 6-значный код
                    await code_input.fill('')
                    await code_input.type(code, delay=50)

                    # Нажимаем подтверждение (для страницы с кодом)
                    if progress_callback:
                        await progress_callback("✅ Отправка кода...")

                    # Пробуем найти кнопку подтверждения на странице с кодом
                    try:
                        confirm_btn = await self.page.wait_for_selector(
                            'button[type="submit"], button:has-text("Подтвердить"), button:has-text("Продолжить")',
                            timeout=3000
                        )
                        await confirm_btn.click()
                        logger.info("🖱 Нажата кнопка подтверждения кода")
                    except:
                        # Если нет кнопки, пробуем Enter
                        await self.page.keyboard.press('Enter')
                        logger.info("⏎ Нажат Enter для подтверждения кода")

                    await asyncio.sleep(3)

            except Exception as e:
                logger.info(f"ℹ️ 2FA не требуется или ошибка: {e}")

            # ===== ВАЖНО: Проверяем страницу MAX =====
            # Проверяем, не попали ли мы на страницу MAX
            current_url = self.page.url
            if "max-account-config" in current_url or "required-action" in current_url:
                # Обрабатываем MAX страницу
                max_handled = await self.handle_max_page(student_id)

                if not max_handled:
                    # Если не смогли обработать MAX, пробуем перейти напрямую
                    logger.warning("⚠️ Не удалось обработать MAX страницу, пробуем прямой переход...")
                    await self.page.goto(
                        'https://pulse.mirea.ru/lessons/visiting-logs/selfapprove',
                        wait_until='domcontentloaded'
                    )

            # ШАГ 7: Переходим на страницу отметок для проверки
            if progress_callback:
                await progress_callback("🔄 Проверка авторизации...")

            await self.page.goto(
                'https://pulse.mirea.ru/lessons/visiting-logs/selfapprove',
                wait_until='domcontentloaded'
            )

            final_url = self.page.url
            logger.info(f"📍 Финальный URL: {final_url}")

            # Проверяем успешность
            if 'login' not in final_url:
                logger.info(f"✅ Авторизация успешна для {student_name}")

                # Сохраняем сессию
                storage_state = await self.context.storage_state()
                session = {
                    'storage_state': storage_state,
                    'user_id': student_id,
                    'timestamp': datetime.now().isoformat(),
                    'student_name': student_name
                }
                await save_session(session)

                if progress_callback:
                    await progress_callback("✅ Сессия сохранена!")

                return {'success': True, 'session': session}
            else:
                raise Exception("Не удалось войти в систему - перенаправлено на страницу входа")

        except Exception as e:
            logger.error(f"❌ Ошибка авторизации: {e}")
            if progress_callback:
                await progress_callback(f"❌ Ошибка: {str(e)[:50]}...")
            return {'success': False, 'error': str(e)}


async def auto_authenticate_student(student_data: dict,
                                    progress_callback=None) -> dict:
    """
    Автоматически авторизует студента в Pulse
    """
    async with PulseAutoAuth(student_data) as auth:
        return await auth.authenticate(progress_callback)


async def update_all_students(students_list: list,
                              progress_callback=None) -> dict:
    """
    Обновляет сессии для всех студентов последовательно
    """
    results = {
        'total': len(students_list),
        'success': 0,
        'failed': 0,
        'details': []
    }

    for i, student in enumerate(students_list, 1):
        student_name = student['name']

        if progress_callback:
            await progress_callback(f"👤 [{i}/{len(students_list)}] {student_name}: начинаю...")

        try:
            result = await auto_authenticate_student(student, progress_callback)

            if result['success']:
                results['success'] += 1
                results['details'].append({
                    'name': student_name,
                    'success': True
                })
                if progress_callback:
                    await progress_callback(f"✅ [{i}/{len(students_list)}] {student_name}: готов")
            else:
                results['failed'] += 1
                results['details'].append({
                    'name': student_name,
                    'success': False,
                    'error': result.get('error')
                })
                if progress_callback:
                    await progress_callback(
                        f"❌ [{i}/{len(students_list)}] {student_name}: {result.get('error', 'ошибка')}")

        except Exception as e:
            results['failed'] += 1
            results['details'].append({
                'name': student_name,
                'success': False,
                'error': str(e)
            })
            if progress_callback:
                await progress_callback(f"❌ [{i}/{len(students_list)}] {student_name}: {str(e)}")

    return results


# Тестовая функция
async def test_auth_for_student(student_id: int):
    """Тестирует авторизацию для конкретного студента"""
    from student_manager import student_manager

    student = student_manager.get_student(student_id)
    if not student:
        print(f"❌ Студент с ID {student_id} не найден")
        return

    print(f"\n🚀 Тест авторизации для {student['name']}")
    print("=" * 50)

    async def progress(msg):
        print(f"📢 {msg}")

    result = await auto_authenticate_student(student, progress)

    print("=" * 50)
    if result['success']:
        print("✅ Тест пройден успешно!")
    else:
        print(f"❌ Ошибка: {result.get('error')}")


async def test_all_students():
    """Тестирует авторизацию для всех студентов"""
    from student_manager import student_manager

    students = student_manager.get_all_students()
    if not students:
        print("❌ Нет студентов в базе")
        return

    print(f"\n🚀 Тест авторизации для {len(students)} студентов")
    print("=" * 50)

    async def progress(msg):
        print(f"📢 {msg}")

    results = await update_all_students(students, progress)

    print("=" * 50)
    print(f"📊 Результаты:")
    print(f"✅ Успешно: {results['success']}")
    print(f"❌ Ошибок: {results['failed']}")
    print(f"📋 Всего: {results['total']}")


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        asyncio.run(test_all_students())
    else:
        asyncio.run(test_auth_for_student(1))