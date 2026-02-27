# student_manager.py
import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class StudentManager:
    """Класс для управления данными студентов"""

    def __init__(self, file_path: str = "students.json"):
        self.file_path = file_path
        self.students = []
        self.load_students()

    def load_students(self) -> List[Dict[str, Any]]:
        """Загружает список студентов из JSON файла"""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.students = data.get('students', [])
                logger.info(f"✅ Загружено {len(self.students)} студентов")
                return self.students
        except FileNotFoundError:
            logger.error(f"❌ Файл {self.file_path} не найден")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON: {e}")
            return []

    def get_student(self, student_id: int) -> Optional[Dict[str, Any]]:
        """Возвращает студента по ID"""
        for student in self.students:
            if student.get('id') == student_id:
                return student
        return None

    def get_all_students(self) -> List[Dict[str, Any]]:
        """Возвращает всех студентов"""
        return self.students

    def get_student_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Возвращает студента по имени"""
        for student in self.students:
            if student.get('name') == name:
                return student
        return None

    def update_student(self, student_id: int, updated_data: Dict[str, Any]) -> bool:
        """Обновляет данные студента"""
        for i, student in enumerate(self.students):
            if student.get('id') == student_id:
                self.students[i].update(updated_data)
                self._save_students()
                logger.info(f"✅ Студент {student_id} обновлен")
                return True
        return False

    def _save_students(self) -> bool:
        """Сохраняет список студентов в JSON файл"""
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump({'students': self.students}, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения: {e}")
            return False

    def add_session_info(self, student_id: int, session_data: Dict[str, Any]) -> bool:
        """Добавляет информацию о сессии для студента"""
        for student in self.students:
            if student.get('id') == student_id:
                if 'sessions' not in student:
                    student['sessions'] = []

                session_info = {
                    'created_at': session_data.get('timestamp'),
                    'expires_at': session_data.get('expires_at'),
                    'session_file': f"session_{student_id}.json"
                }
                student['sessions'].append(session_info)

                if len(student['sessions']) > 10:
                    student['sessions'] = student['sessions'][-10:]

                self._save_students()
                return True
        return False

    async def get_session_status(self, student_id: int) -> Dict[str, Any]:
        """Возвращает статус сессии студента"""
        from session_manager import load_session
        import os
        from datetime import datetime

        session_file = f"session_{student_id}.json"

        if not os.path.exists(session_file):
            return {
                'status': 'no_session',
                'message': 'Сессия отсутствует'
            }

        session = await load_session(student_id)  # ✅ Добавлен await
        if not session:
            return {
                'status': 'error',
                'message': 'Ошибка загрузки сессии'
            }

        timestamp = session.get('timestamp')
        if timestamp:
            created = datetime.fromisoformat(timestamp)
            now = datetime.now()
            age = (now - created).total_seconds() / 3600

            if age < 2:
                return {
                    'status': 'active',
                    'created': created,
                    'age_hours': round(age, 1),
                    'expires_in': f"{round(2 - age, 1)} ч"
                }
            else:
                return {
                    'status': 'expired',
                    'created': created,
                    'age_hours': round(age, 1),
                    'message': 'Сессия истекла'
                }

        return {
            'status': 'unknown',
            'message': 'Неизвестный статус'
        }


# Создаем глобальный экземпляр
student_manager = StudentManager()