# email_imap.py
import asyncio
import imaplib
import time
import logging
import re
import email
from email.header import decode_header
from typing import Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def decode_str(text):
    """Декодирует строку из почтового формата"""
    try:
        decoded = decode_header(text)[0]
        if isinstance(decoded[0], bytes):
            return decoded[0].decode(decoded[1] or 'utf-8', errors='ignore')
        return decoded[0]
    except:
        return text


def get_email_body(msg):
    """Извлекает тело письма"""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except:
                    continue
    else:
        try:
            return msg.get_payload(decode=True).decode('utf-8', errors='ignore')
        except:
            return msg.get_payload()
    return ""


class YandexIMAP:
    """Класс для работы с Яндекс Почтой через IMAP"""

    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.imap_server = "imap.yandex.ru"
        self.imap_port = 993
        self.connection = None
        self.is_connected = False

    def connect(self) -> bool:
        """Подключается к Яндекс Почте"""
        if self.is_connected and self.connection:
            try:
                self.connection.noop()
                return True
            except:
                self.is_connected = False
                self.connection = None

        try:
            self.connection = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            self.connection.login(self.email, self.password)
            self.is_connected = True
            logger.info(f"✅ Подключено к почте {self.email}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к почте: {e}")
            return False

    def disconnect(self):
        """Закрывает соединение"""
        if self.connection and self.is_connected:
            try:
                self.connection.close()
                self.connection.logout()
            except:
                pass
            finally:
                self.is_connected = False
                self.connection = None

    def find_letter_by_id(self, letter_id: str, minutes_back: int = 30) -> Optional[str]:
        """
        Ищет письмо, содержащее указанный двухзначный идентификатор
        """
        if not self.connect():
            return None

        try:
            # Выбираем папку "Входящие"
            self.connection.select('INBOX')

            # Ищем ВСЕ письма за последние N минут
            since_date = (datetime.now() - timedelta(minutes=minutes_back)).strftime("%d-%b-%Y")
            search_criteria = f'(SINCE {since_date})'

            status, messages = self.connection.uid('SEARCH', None, search_criteria)

            if status != 'OK' or not messages[0]:
                return None

            uid_list = messages[0].split()
            clean_id = letter_id.replace('#', '')

            # Проверяем все письма
            for uid in reversed(uid_list):
                status, data = self.connection.uid('FETCH', uid, '(RFC822)')
                if status == 'OK':
                    msg = email.message_from_bytes(data[0][1])

                    # Получаем тему и тело
                    subject = decode_str(msg.get('Subject', ''))
                    body = get_email_body(msg)

                    # Ищем идентификатор в теме или теле
                    if (f"({clean_id})" in body or
                            f"#{clean_id}" in body or
                            f"#{clean_id}" in subject):
                        logger.info(f"✅ Найдено письмо с идентификатором {letter_id}")
                        return body  # Возвращаем тело письма

            return None

        except Exception as e:
            logger.error(f"❌ Ошибка при поиске письма: {e}")
            return None

    @staticmethod
    def extract_six_digit_code(email_body: str) -> Optional[str]:
        """
        Извлекает 6-значный код из тела письма
        """
        if not email_body:
            return None

        # Паттерны для поиска 6-значного кода
        patterns = [
            r'(\d{6})\s*–',  # 917479 –
            r'Введите\s+код\s+(\d{6})',  # Введите код 917479
            r'код\s+(\d{6})',  # код 917479
            r'\b(\d{6})\b',  # 917479
        ]

        for pattern in patterns:
            matches = re.findall(pattern, email_body)
            if matches:
                code = matches[0]
                logger.info(f"✅ Найден код: {code}")
                return code

        return None


# ============================================
# АСИНХРОННЫЕ ФУНКЦИИ ДЛЯ БОТА
# ============================================

async def find_letter_by_id_and_get_code(yandex_email: str, yandex_password: str,
                                         letter_id: str, timeout: int = 120,
                                         check_interval: int = 5) -> Optional[str]:
    """
    Ищет письмо по двухзначному идентификатору и извлекает из него 6-значный код
    """
    logger.info(f"🔍 Поиск письма с идентификатором {letter_id} в почте {yandex_email}")

    start_time = time.time()
    imap_client = YandexIMAP(yandex_email, yandex_password)

    try:
        if not imap_client.connect():
            logger.error("❌ Не удалось подключиться к почте")
            return None

        while time.time() - start_time < timeout:
            elapsed = int(time.time() - start_time)

            email_body = imap_client.find_letter_by_id(letter_id)

            if email_body:
                logger.info(f"📧 Письмо найдено на {elapsed} секунде")
                code = imap_client.extract_six_digit_code(email_body)

                if code:
                    logger.info(f"✅ Успешно получен код {code}")
                    return code

            logger.info(f"⏳ Проверка почты... прошло {elapsed} сек")
            await asyncio.sleep(check_interval)

        logger.warning(f"⏰ Таймаут {timeout} сек")
        return None

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return None
    finally:
        imap_client.disconnect()