#session_manager
import json
import os
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


async def save_session(session: dict):
    """Сохраняет сессию пользователя в файл"""
    user_id = session.get('user_id')
    if not user_id:
        return

    filename = f'session_{user_id}.json'
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
        logger.info(f"Сессия для пользователя {user_id} сохранена")
    except Exception as e:
        logger.error(f"Ошибка при сохранении сессии: {e}")


async def load_session(user_id: int) -> Optional[dict]:
    """Загружает сессию пользователя из файла"""
    filename = f'session_{user_id}.json'
    if not os.path.exists(filename):
        return None

    try:
        with open(filename, 'r', encoding='utf-8') as f:
            session = json.load(f)
        logger.info(f"Сессия для пользователя {user_id} загружена")
        return session
    except Exception as e:
        logger.error(f"Ошибка при загрузке сессии: {e}")
        return None