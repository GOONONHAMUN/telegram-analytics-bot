import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram Bot Token (от @BotFather)
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
    # Telegram API (от my.telegram.org)
    API_ID = int(os.getenv('API_ID', 0))
    API_HASH = os.getenv('API_HASH', '')
    
    # Настройки базы данных
    DB_PATH = os.getenv('DB_PATH', 'bot_database.db')
    
    # Администраторы
    ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()]
    
    # Настройки сбора статистики
    UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', '300'))  # 5 минут
    
    @classmethod
    def validate(cls):
        """Проверка конфигурации"""
        errors = []
        if not cls.BOT_TOKEN:
            errors.append("BOT_TOKEN не установлен")
        if not cls.API_ID:
            errors.append("API_ID не установлен")
        if not cls.API_HASH:
            errors.append("API_HASH не установлен")
        
        if errors:
            raise ValueError(f"Ошибки конфигурации: {', '.join(errors)}")
