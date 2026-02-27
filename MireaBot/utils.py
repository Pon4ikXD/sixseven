#utils.py
import random
import string


def generate_session_id() -> str:
    """Генерирует уникальный ID сессии"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=32))


def extract_qr_data(qr_content: str) -> dict:
    """
    Пытается извлечь данные из QR-кода
    Предполагается, что QR содержит URL с параметрами
    """
    import urllib.parse

    parsed = urllib.parse.urlparse(qr_content)
    params = urllib.parse.parse_qs(parsed.query)

    # Пытаемся найти токен или ID пары
    result = {
        'raw': qr_content,
        'url': qr_content,
        'params': params
    }

    # Если есть токен в параметрах, выделяем его
    if 'token' in params:
        result['token'] = params['token'][0]
    elif 'code' in params:
        result['code'] = params['code'][0]

    return result