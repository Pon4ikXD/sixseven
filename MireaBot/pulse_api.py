# pulse_api.py
import asyncio
import json
import logging
import base64
import struct
import urllib.parse
from typing import Dict, Any

logger = logging.getLogger(__name__)


def create_grpc_request(qr_data: str) -> bytes:
    """
    Создает gRPC-web запрос для SelfApproveAttendanceThroughQRCode
    Формат: https://github.com/grpc/grpc-web
    """
    # Извлекаем токен из QR-кода
    token = extract_token_from_qr(qr_data)

    # Формируем protobuf сообщение
    # Поле 1: токен (string) - 0x0A = (1 << 3) | 2
    token_bytes = token.encode('utf-8')

    # Формируем protobuf: [field_key][length][value]
    protobuf_msg = bytes([0x0A]) + _encode_varint(len(token_bytes)) + token_bytes

    # Формируем gRPC-web фрейм
    # [flag:1byte][length:4bytes][message]
    grpc_frame = b'\x00' + struct.pack('>I', len(protobuf_msg)) + protobuf_msg

    return grpc_frame


def _encode_varint(value: int) -> bytes:
    """Кодирует число как protobuf varint"""
    result = []
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            result.append(byte | 0x80)
        else:
            result.append(byte)
            break
    return bytes(result)


def extract_token_from_qr(qr_data: str) -> str:
    """
    Извлекает токен из QR-кода.
    QR-код содержит URL вида:
    https://attendance-app.mirea.ru/?token=ABC123XYZ
    """
    # Пробуем распарсить как URL
    try:
        parsed = urllib.parse.urlparse(qr_data)
        params = urllib.parse.parse_qs(parsed.query)

        # Ищем токен в параметрах
        if 'token' in params:
            return params['token'][0]
        if 'code' in params:
            return params['code'][0]
        if 't' in params:
            return params['t'][0]
    except:
        pass

    # Если это просто строка, возможно это сам токен
    return qr_data


def extract_cookies_from_storage(storage_state: Dict) -> Dict[str, str]:
    """Извлекает cookies из storage_state Playwright"""
    cookies = {}

    if 'cookies' in storage_state:
        for cookie in storage_state['cookies']:
            if 'name' in cookie and 'value' in cookie:
                cookies[cookie['name']] = cookie['value']

    return cookies


async def send_qr_to_pulse(user_id: int, qr_data: str) -> Dict[str, Any]:
    """
    Отправляет QR-код в Pulse через gRPC-web API
    """
    logger.info(f"📤 Отправка QR-кода в Pulse для пользователя {user_id}")

    # Загружаем сессию пользователя
    from session_manager import load_session
    session_data = await load_session(user_id)

    if not session_data:
        logger.error(f"❌ Сессия не найдена для пользователя {user_id}")
        return {
            'success': False,
            'error': 'Сессия не найдена. Требуется переавторизация.',
            'need_reauth': True
        }

    # Извлекаем токен
    token = extract_token_from_qr(qr_data)
    logger.info(f"🔑 Извлечен токен: {token[:20]}...")

    # Получаем cookies из сессии
    cookies = extract_cookies_from_storage(session_data.get('storage_state', {}))

    # Создаем gRPC запрос
    grpc_data = create_grpc_request(qr_data)

    # Заголовки как в оригинальном запросе
    headers = {
        'Content-Type': 'application/grpc-web+proto',
        'X-Grpc-Web': '1',
        'Pulse-App-Type': 'pulse-app',
        'Pulse-App-Version': '1.6.2+5491',
        'Accept': '*/*',
        'Origin': 'https://attendance-app.mirea.ru',
        'Referer': 'https://attendance-app.mirea.ru/',
        'Accept-Language': 'ru,en-US;q=0.9,en;q=0.8,nl;q=0.7',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
        'X-Requested-With': 'XMLHttpRequest'
    }

    # URL эндпоинта
    url = "https://attendance.mirea.ru/rtu_tc.attendance.api.AttendanceService/SelfApproveAttendanceThroughQRCode"

    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    url,
                    data=grpc_data,
                    headers=headers,
                    cookies=cookies,
                    timeout=30
            ) as response:

                # Проверяем статус
                if response.status == 200:
                    # Читаем ответ (gRPC-web формат)
                    resp_data = await response.read()

                    # Парсим gRPC ответ
                    # Первый байт - флаг, затем 4 байта длины
                    if len(resp_data) > 5:
                        # Пропускаем флаг и длину
                        protobuf_response = resp_data[5:]

                        logger.info(f"✅ Успешный ответ от Pulse, длина: {len(resp_data)}")

                        return {
                            'success': True,
                            'message': '✅ Вы успешно отметились на паре!',
                            'data': base64.b64encode(resp_data).decode()[:100]
                        }
                    else:
                        return {
                            'success': True,
                            'message': '✅ Отметка принята'
                        }

                elif response.status == 401:
                    logger.warning(f"⚠️ Сессия устарела для пользователя {user_id}")
                    return {
                        'success': False,
                        'error': 'Сессия устарела. Требуется переавторизация.',
                        'need_reauth': True
                    }
                else:
                    text = await response.text()
                    logger.error(f"❌ Ошибка Pulse API: {response.status} - {text[:200]}")
                    return {
                        'success': False,
                        'error': f'Ошибка сервера: {response.status}'
                    }

    except ImportError:
        logger.error("❌ Библиотека aiohttp не установлена")
        return {
            'success': False,
            'error': 'Ошибка конфигурации сервера'
        }
    except aiohttp.ClientError as e:
        logger.error(f"❌ Ошибка соединения: {e}")
        return {
            'success': False,
            'error': 'Ошибка соединения с сервером'
        }
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка: {e}")
        return {
            'success': False,
            'error': str(e)
        }


async def test_pulse_connection(user_id: int) -> Dict[str, Any]:
    """
    Тестирует соединение с Pulse API
    """
    from session_manager import load_session
    session_data = await load_session(user_id)

    if not session_data:
        return {'success': False, 'error': 'Нет сессии'}

    cookies = extract_cookies_from_storage(session_data.get('storage_state', {}))

    # Пробуем сделать OPTIONS запрос как в логах
    url = "https://attendance.mirea.ru/rtu_tc.attendance.api.AttendanceService/SelfApproveAttendanceThroughQRCode"

    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            # OPTIONS запрос для проверки CORS
            async with session.options(url, headers={
                'Origin': 'https://attendance-app.mirea.ru',
                'Access-Control-Request-Method': 'POST',
                'Access-Control-Request-Headers': 'content-type,x-grpc-web,pulse-app-type,pulse-app-version,sentry-trace,baggage,x-requested-with'
            }) as response:

                if response.status == 204:
                    logger.info("✅ OPTIONS запрос успешен")
                    return {'success': True, 'message': 'API доступно'}
                else:
                    return {'success': False, 'error': f'OPTIONS вернул {response.status}'}

    except ImportError:
        return {'success': False, 'error': 'aiohttp не установлен'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


async def mark_all_students(qr_data: str) -> Dict[str, Any]:
    """
    Отправляет отметку для всех студентов параллельно

    Args:
        qr_data: Данные из QR-кода

    Returns:
        Dict с результатами по всем студентам
    """
    from student_manager import student_manager

    students = student_manager.get_all_students()

    if not students:
        return {
            'success': False,
            'error': 'Нет студентов в базе',
            'total': 0,
            'success_count': 0,
            'failed_count': 0
        }

    logger.info(f"📤 Отправка отметки для {len(students)} студентов")

    # Запускаем все запросы параллельно
    tasks = [send_qr_to_pulse(s['id'], qr_data) for s in students]
    results = await asyncio.gather(*tasks)

    # Анализируем результаты
    success_count = 0
    failed_count = 0
    need_reauth_list = []
    failed_list = []
    already_marked_count = 0

    for i, result in enumerate(results):
        student = students[i]
        student_name = student['name']

        if result['success']:
            success_count += 1
        else:
            if result.get('need_reauth'):
                need_reauth_list.append({
                    'name': student_name,
                    'id': student['id']
                })
            else:
                failed_count += 1
                failed_list.append({
                    'name': student_name,
                    'id': student['id'],
                    'error': result.get('error', 'Неизвестная ошибка')
                })

            # Если ошибка "уже отмечен" — считаем как успех
            if result.get('error') and 'уже' in result.get('error', '').lower():
                already_marked_count += 1
                success_count += 1  # Технически это успех

    return {
        'total': len(students),
        'success': success_count,
        'failed': failed_count,
        'already_marked': already_marked_count,
        'need_reauth': len(need_reauth_list),
        'need_reauth_list': need_reauth_list,
        'failed_list': failed_list,
        'details': results
    }