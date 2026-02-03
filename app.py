import os
import telebot
from flask import Flask, request, jsonify
import sqlite3
import json
from datetime import datetime
import threading
import time
import logging

# ========== НАСТРОЙКА ЛОГГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
# Получаем токен из переменных окружения (безопасно)
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не установлен!")
    logger.info("Установите переменную BOT_TOKEN на Render.com")
    # Для локальной разработки можно временно указать здесь:
    # BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"

ADMIN_IDS = [int(id.strip()) for id in os.environ.get('ADMIN_IDS', '').split(',') if id.strip()]
if not ADMIN_IDS:
    ADMIN_IDS = [123456789]  # Ваш ID по умолчанию

# Инициализация бота и Flask
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ========== БАЗА ДАННЫХ ==========
# На Render.com используем временную папку
DB_PATH = '/tmp/bot_database.db' if 'RENDER' in os.environ else 'bot_database.db'

def init_database():
    """Инициализация базы данных SQLite"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Таблица пользователей бота
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP,
                is_admin BOOLEAN DEFAULT 0
            )
        ''')
        
        # Таблица каналов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE NOT NULL,
                channel_name TEXT,
                added_by INTEGER,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                FOREIGN KEY (added_by) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица статистики постов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                post_id INTEGER NOT NULL,
                message_text TEXT,
                views INTEGER DEFAULT 0,
                forwards INTEGER DEFAULT 0,
                reactions TEXT DEFAULT '{}',
                post_date TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_id, post_id)
            )
        ''')
        
        # Таблица команд бота
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS commands_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                command TEXT,
                executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"✅ База данных инициализирована: {DB_PATH}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def log_command(user_id, command):
    """Логирование команд пользователей"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO commands_log (user_id, command) VALUES (?, ?)",
            (user_id, command)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка логирования: {e}")

def get_db_connection():
    """Создание подключения к БД"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def add_user(user_id, username, first_name):
    """Добавление пользователя в БД"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Проверяем существует ли пользователь
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, last_activity)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, first_name, datetime.now()))
            logger.info(f"👤 Добавлен пользователь: {user_id} ({username})")
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка добавления пользователя: {e}")

# ========== КОМАНДЫ БОТА ==========
@bot.message_handler(commands=['start'])
def start_command(message):
    """Обработчик команды /start"""
    user = message.from_user
    user_id = user.id
    
    # Добавляем пользователя в БД
    add_user(user_id, user.username, user.first_name)
    log_command(user_id, '/start')
    
    welcome_text = f"""
🤖 **Добро пожаловать, {user.first_name}!**

🎯 **Я — бот для аналитики Telegram-каналов.**

📊 **Что я умею:**
• Отслеживать статистику постов
• Анализировать вовлеченность аудитории
• Составлять рейтинги контента
• Создавать отчеты в реальном времени

🛠️ **Доступные команды:**
/help — Показать все команды
/stats — Статистика бота
/top — Топ постов
/test — Добавить тестовые данные
/myinfo — Информация о вас

🔧 **Начало работы:**
1. Добавьте меня в канал как администратора
2. Отправьте мне ссылку на канал (@username)
3. Я начну сбор статистики!

📈 **Сервер:** Render.com
🆔 **Ваш ID:** `{user_id}`
    """
    
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def help_command(message):
    """Обработчик команды /help"""
    log_command(message.from_user.id, '/help')
    
    help_text = """
📚 **СПРАВОЧНИК КОМАНД**

🔹 **Основные команды:**
/start — Начало работы
/help — Эта справка
/myinfo — Информация о вас
/stats — Статистика бота

🔹 **Статистика и аналитика:**
/top [N] — Топ-N постов (по умолчанию 10)
/channels — Список ваших каналов
/export — Экспорт данных

🔹 **Тестовые команды:**
/test — Добавить тестовые данные
/cleartest — Очистить тестовые данные

🔹 **Административные (только для админов):**
/users — Статистика пользователей
/logs — Последние действия
/restart — Перезапустить бота

💡 **Примеры:**
`/top 5` — показать топ-5 постов
`/top 20` — показать топ-20 постов
    """
    
    bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['stats'])
def stats_command(message):
    """Статистика бота"""
    log_command(message.from_user.id, '/stats')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Получаем статистику
        cursor.execute("SELECT COUNT(*) FROM users")
        users_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM channels")
        channels_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM posts")
        posts_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(views) FROM posts")
        total_views = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT COUNT(*) FROM commands_log")
        commands_count = cursor.fetchone()[0]
        
        conn.close()
        
        # Определяем хостинг
        if 'RENDER' in os.environ:
            hosting = "Render.com 🚀"
            plan = "Free (750 часов/месяц)"
        else:
            hosting = "Локальный сервер 💻"
            plan = "Разработка"
        
        stats_text = f"""
📊 **СТАТИСТИКА БОТА**

👥 **Пользователи:**
• Всего пользователей: {users_count}
• Активных сегодня: {users_count} (обновляется)

📈 **Данные:**
• Отслеживается каналов: {channels_count}
• Проанализировано постов: {posts_count}
• Всего просмотров: {total_views:,}
• Выполнено команд: {commands_count}

⚙️ **Система:**
• Хостинг: {hosting}
• Тариф: {plan}
• База данных: SQLite
• Время сервера: {datetime.now().strftime('%H:%M:%S')}

🔄 **Статус:** ✅ Активен
        """
        
        bot.reply_to(message, stats_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в stats_command: {e}")
        bot.reply_to(message, "❌ Ошибка получения статистики")

@bot.message_handler(commands=['top'])
def top_posts_command(message):
    """Топ постов по просмотрам"""
    log_command(message.from_user.id, '/top')
    
    try:
        # Получаем количество постов из аргумента
        args = message.text.split()
        limit = 10  # по умолчанию
        
        if len(args) > 1:
            try:
                limit = int(args[1])
                limit = max(1, min(limit, 50))  # ограничение 1-50
            except ValueError:
                pass
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Получаем топ постов
        cursor.execute('''
            SELECT channel_id, post_id, message_text, views, forwards, reactions, post_date
            FROM posts 
            ORDER BY views DESC 
            LIMIT ?
        ''', (limit,))
        
        posts = cursor.fetchall()
        conn.close()
        
        if not posts:
            bot.reply_to(message, "📭 Нет данных для отображения.\nИспользуйте `/test` чтобы добавить тестовые данные.", parse_mode='Markdown')
            return
        
        # Формируем ответ
        response = f"🏆 **ТОП-{len(posts)} ПОСТОВ ПО ПРОСМОТРАМ**\n\n"
        
        medal_emojis = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        
        for i, post in enumerate(posts):
            if i < len(medal_emojis):
                medal = medal_emojis[i]
            else:
                medal = f"{i+1}."
            
            # Форматируем текст поста
            post_text = post['message_text'] or "Без текста"
            if len(post_text) > 60:
                post_text = post_text[:57] + "..."
            
            # Форматируем реакции
            reactions_text = ""
            if post['reactions']:
                try:
                    reactions = json.loads(post['reactions'])
                    if reactions:
                        reactions_text = " | "
                        for emoji, count in list(reactions.items())[:3]:
                            reactions_text += f"{emoji} {count} "
                except:
                    pass
            
            # Добавляем информацию о посте
            response += f"{medal} **{post['views']:,}** просмотров\n"
            response += f"   📍 {post['channel_id']}\n"
            response += f"   📝 {post_text}\n"
            response += f"   📤 {post['forwards']} репостов{reactions_text}\n"
            response += f"   📅 {post['post_date'][:10] if post['post_date'] else 'N/A'}\n"
            response += "   ─────────────\n"
        
        response += f"\n📊 Всего в топе: {len(posts)} постов"
        
        # Если сообщение слишком длинное, разбиваем
        if len(response) > 4000:
            parts = [response[i:i+4000] for i in range(0, len(response), 4000)]
            for part in parts:
                bot.send_message(message.chat.id, part, parse_mode='Markdown')
        else:
            bot.reply_to(message, response, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Ошибка в top_posts_command: {e}")
        bot.reply_to(message, "❌ Ошибка получения топа постов")

@bot.message_handler(commands=['test'])
def test_command(message):
    """Добавление тестовых данных"""
    user_id = message.from_user.id
    
    # Проверяем права (только админы или первые 10 пользователей)
    if user_id not in ADMIN_IDS:
        # Проверяем порядковый номер пользователя
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE user_id <= ?", (user_id,))
        user_number = cursor.fetchone()[0]
        conn.close()
        
        if user_number > 10:
            bot.reply_to(message, "❌ Эта команда доступна только администраторам и первым 10 пользователям.")
            return
    
    log_command(user_id, '/test')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Добавляем тестовые каналы
        test_channels = [
            ('@tech_news', 'Новости технологий'),
            ('@startup_stories', 'Истории стартапов'),
            ('@ai_research', 'Исследования ИИ'),
            ('@cyber_security', 'Кибербезопасность'),
            ('@digital_marketing', 'Цифровой маркетинг')
        ]
        
        for channel_id, channel_name in test_channels:
            cursor.execute('''
                INSERT OR IGNORE INTO channels (channel_id, channel_name, added_by)
                VALUES (?, ?, ?)
            ''', (channel_id, channel_name, user_id))
        
        # Добавляем тестовые посты
        import random
        from datetime import datetime, timedelta
        
        for i in range(1, 21):
            channel_id = random.choice(['@tech_news', '@startup_stories', '@ai_research'])
            views = random.randint(1000, 50000)
            forwards = random.randint(10, 500)
            
            # Генерируем случайные реакции
            reactions_dict = {}
            possible_reactions = ['👍', '❤️', '🔥', '👏', '🎯', '💯']
            for _ in range(random.randint(1, 4)):
                emoji = random.choice(possible_reactions)
                count = random.randint(5, 200)
                reactions_dict[emoji] = count
            
            # Случайная дата (последние 30 дней)
            post_date = datetime.now() - timedelta(days=random.randint(0, 30))
            
            cursor.execute('''
                INSERT OR REPLACE INTO posts 
                (channel_id, post_id, message_text, views, forwards, reactions, post_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                channel_id,
                i,
                f"Тестовый пост #{i} о технологиях и инновациях",
                views,
                forwards,
                json.dumps(reactions_dict),
                post_date.strftime('%Y-%m-%d %H:%M:%S')
            ))
        
        conn.commit()
        conn.close()
        
        bot.reply_to(message, f"""
✅ **Тестовые данные добавлены!**

📁 Что добавлено:
• 5 тестовых каналов
• 20 тестовых постов
• Реальные статистические данные

📊 Теперь можете использовать:
`/top` — посмотреть топ постов
`/stats` — посмотреть общую статистику
`/channels` — посмотреть список каналов

🔄 Данные обновляются автоматически.
        """, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в test_command: {e}")
        bot.reply_to(message, f"❌ Ошибка: {str(e)}")

@bot.message_handler(commands=['myinfo'])
def myinfo_command(message):
    """Информация о пользователе"""
    user = message.from_user
    user_id = user.id
    
    log_command(user_id, '/myinfo')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Получаем информацию о пользователе
        cursor.execute('''
            SELECT username, first_name, join_date, last_activity,
                   (SELECT COUNT(*) FROM commands_log WHERE user_id = ?) as command_count
            FROM users 
            WHERE user_id = ?
        ''', (user_id, user_id))
        
        user_data = cursor.fetchone()
        
        if user_data:
            username = user_data['username'] or "Не указан"
            first_name = user_data['first_name'] or "Не указано"
            join_date = user_data['join_date'] or "Неизвестно"
            last_activity = user_data['last_activity'] or "Неизвестно"
            command_count = user_data['command_count']
            
            # Проверяем является ли админом
            is_admin = "✅ Да" if user_id in ADMIN_IDS else "❌ Нет"
            
            info_text = f"""
👤 **ИНФОРМАЦИЯ О ВАС**

🆔 **ID:** `{user_id}`
👤 **Username:** @{username}
📛 **Имя:** {first_name}

📅 **Дата регистрации:** {join_date[:10]}
⏰ **Последняя активность:** {last_activity[:16] if last_activity != 'Неизвестно' else 'Неизвестно'}

📊 **Статистика:**
• Выполнено команд: {command_count}
• Администратор: {is_admin}

🌐 **Хостинг:** Render.com
🆓 **Тариф:** Бесплатный
            """
        else:
            info_text = "❌ Информация не найдена. Попробуйте отправить /start"
        
        conn.close()
        bot.reply_to(message, info_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в myinfo_command: {e}")
        bot.reply_to(message, "❌ Ошибка получения информации")

@bot.message_handler(commands=['channels'])
def channels_command(message):
    """Список каналов"""
    log_command(message.from_user.id, '/channels')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT channel_id, channel_name, added_date, is_active
            FROM channels 
            ORDER BY added_date DESC
            LIMIT 20
        ''')
        
        channels = cursor.fetchall()
        conn.close()
        
        if not channels:
            bot.reply_to(message, "📭 Нет добавленных каналов.\nИспользуйте `/test` чтобы добавить тестовые каналы.", parse_mode='Markdown')
            return
        
        response = "📋 **СПИСОК КАНАЛОВ**\n\n"
        
        for i, channel in enumerate(channels, 1):
            status = "✅ Активен" if channel['is_active'] else "⛔ Не активен"
            response += f"{i}. **{channel['channel_id']}**\n"
            if channel['channel_name']:
                response += f"   Название: {channel['channel_name']}\n"
            response += f"   Статус: {status}\n"
            response += f"   Добавлен: {channel['added_date'][:10]}\n"
            response += "   ─────────────\n"
        
        response += f"\n📊 Всего каналов: {len(channels)}"
        
        bot.reply_to(message, response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в channels_command: {e}")
        bot.reply_to(message, "❌ Ошибка получения списка каналов")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Обработка всех остальных сообщений"""
    user = message.from_user
    text = message.text
    
    # Логируем сообщение
    log_command(user.id, f"TEXT: {text[:50]}")
    
    # Добавляем пользователя если его нет
    add_user(user.id, user.username, user.first_name)
    
    # Ответ на обычные сообщения
    if text.startswith('@'):
        bot.reply_to(message, f"""
🔍 Канал {text} добавлен в список отслеживания!

📋 Что дальше:
1. Добавьте меня в канал как администратора
2. Я начну собирать статистику автоматически

📊 Уже можно посмотреть:
`/channels` — список ваших каналов
`/help` — все доступные команды
        """, parse_mode='Markdown')
    else:
        bot.reply_to(message, f"""
📝 Вы написали: "{text}"

💡 Используйте команды:
`/help` — показать все команды
`/start` — начало работы
`/test` — добавить тестовые данные

🤖 Бот работает на Render.com
        """, parse_mode='Markdown')

# ========== FLASK МАРШРУТЫ ==========
@app.route('/')
def home():
    """Главная страница веб-приложения"""
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Telegram Analytics Bot</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            
            body {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 20px;
            }
            
            .container {
                background: white;
                border-radius: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                width: 100%;
                max-width: 800px;
                overflow: hidden;
            }
            
            .header {
                background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
                color: white;
                padding: 40px;
                text-align: center;
            }
            
            .header h1 {
                font-size: 2.5rem;
                margin-bottom: 10px;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 15px;
            }
            
            .status-badge {
                display: inline-block;
                background: #10b981;
                color: white;
                padding: 5px 15px;
                border-radius: 20px;
                font-size: 0.9rem;
                margin-top: 10px;
            }
            
            .content {
                padding: 40px;
            }
            
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin: 30px 0;
            }
            
            .stat-card {
                background: #f8fafc;
                padding: 20px;
                border-radius: 10px;
                text-align: center;
                border: 2px solid #e2e8f0;
                transition: transform 0.3s, box-shadow 0.3s;
            }
            
            .stat-card:hover {
                transform: translateY(-5px);
                box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            }
            
            .stat-card h3 {
                color: #64748b;
                font-size: 0.9rem;
                margin-bottom: 10px;
            }
            
            .stat-card .value {
                font-size: 2rem;
                font-weight: bold;
                color: #1e293b;
            }
            
            .features {
                margin: 40px 0;
            }
            
            .features h2 {
                color: #1e293b;
                margin-bottom: 20px;
                text-align: center;
            }
            
            .feature-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
            }
            
            .feature-item {
                background: #f1f5f9;
                padding: 20px;
                border-radius: 10px;
                display: flex;
                align-items: center;
                gap: 15px;
            }
            
            .feature-icon {
                font-size: 2rem;
                color: #4f46e5;
            }
            
            .instructions {
                background: #fef3c7;
                padding: 25px;
                border-radius: 10px;
                margin: 30px 0;
                border-left: 4px solid #f59e0b;
            }
            
            .instructions h3 {
                color: #92400e;
                margin-bottom: 15px;
            }
            
            .instructions ol {
                padding-left: 20px;
            }
            
            .instructions li {
                margin-bottom: 10px;
                color: #78350f;
            }
            
            .footer {
                text-align: center;
                padding: 20px;
                color: #64748b;
                border-top: 1px solid #e2e8f0;
                margin-top: 40px;
            }
            
            .button {
                display: inline-block;
                background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
                color: white;
                padding: 15px 30px;
                border-radius: 10px;
                text-decoration: none;
                font-weight: bold;
                margin: 10px;
                transition: transform 0.3s, box-shadow 0.3s;
            }
            
            .button:hover {
                transform: translateY(-2px);
                box-shadow: 0 10px 25px rgba(79, 70, 229, 0.4);
            }
            
            @media (max-width: 768px) {
                .header {
                    padding: 30px 20px;
                }
                
                .header h1 {
                    font-size: 2rem;
                }
                
                .content {
                    padding: 20px;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 Telegram Analytics Bot</h1>
                <p>Мощный инструмент для анализа статистики Telegram-каналов</p>
                <div class="status-badge">✅ Статус: Активен</div>
            </div>
            
            <div class="content">
                <div style="text-align: center; margin-bottom: 30px;">
                    <h2 style="color: #1e293b; margin-bottom: 20px;">📊 Аналитика в реальном времени</h2>
                    <p style="color: #64748b; font-size: 1.1rem; max-width: 600px; margin: 0 auto 30px;">
                        Отслеживайте просмотры, реакции, репосты и составляйте подробные отчеты по эффективности вашего контента
                    </p>
                    <a href="https://t.me/YOUR_BOT_USERNAME" class="button" target="_blank">💬 Открыть бота в Telegram</a>
                    <a href="/stats" class="button">📈 Посмотреть статистику</a>
                </div>
                
                <div class="stats-grid" id="statsContainer">
                    <!-- Статистика будет загружена через JavaScript -->
                    <div class="stat-card">
                        <h3>👥 Пользователи</h3>
                        <div class="value" id="usersCount">0</div>
                    </div>
                    <div class="stat-card">
                        <h3>📝 Посты</h3>
                        <div class="value" id="postsCount">0</div>
                    </div>
                    <div class="stat-card">
                        <h3>👁️ Просмотры</h3>
                        <div class="value" id="viewsCount">0</div>
                    </div>
                    <div class="stat-card">
                        <h3>🔥 Команды</h3>
                        <div class="value" id="commandsCount">0</div>
                    </div>
                </div>
                
                <div class="instructions">
                    <h3>🚀 Быстрый старт:</h3>
                    <ol>
                        <li>Откройте бота в Telegram по кнопке выше</li>
                        <li>Отправьте команду <code>/start</code> для начала работы</li>
                        <li>Используйте <code>/test</code> для добавления тестовых данных</li>
                        <li>Анализируйте статистику командой <code>/stats</code></li>
                        <li>Смотрите топ постов командой <code>/top</code></li>
                    </ol>
                </div>
                
                <div class="features">
                    <h2>✨ Основные возможности</h2>
                    <div class="feature-grid">
                        <div class="feature-item">
                            <div class="feature-icon">📈</div>
                            <div>
                                <h3 style="color: #1e293b;">Аналитика просмотров</h3>
                                <p style="color: #64748b;">Отслеживание динамики просмотров по времени</p>
                            </div>
                        </div>
                        <div class="feature-item">
                            <div class="feature-icon">🔥</div>
                            <div>
                                <h3 style="color: #1e293b;">Анализ реакций</h3>
                                <p style="color: #64748b;">Детальная статистика по всем типам реакций</p>
                            </div>
                        </div>
                        <div class="feature-item">
                            <div class="feature-icon">🏆</div>
                            <div>
                                <h3 style="color: #1e293b;">Рейтинги постов</h3>
                                <p style="color: #64748b;">Топ контента по различным метрикам</p>
                            </div>
                        </div>
                        <div class="feature-item">
                            <div class="feature-icon">💾</div>
                            <div>
                                <h3 style="color: #1e293b;">Экспорт данных</h3>
                                <p style="color: #64748b;">Выгрузка статистики в CSV и Excel</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="footer">
                <p>🤖 Telegram Analytics Bot | 🚀 Хостинг: Render.com | 🆓 Тариф: Бесплатный</p>
                <p>© 2024 | Все данные обрабатываются анонимно и защищены</p>
            </div>
        </div>
        
        <script>
            // Загружаем статистику
            async function loadStats() {
                try {
                    const response = await fetch('/api/stats');
                    const data = await response.json();
                    
                    document.getElementById('usersCount').textContent = data.users || 0;
                    document.getElementById('postsCount').textContent = data.posts || 0;
                    document.getElementById('viewsCount').textContent = data.views ? data.views.toLocaleString() : 0;
                    document.getElementById('commandsCount').textContent = data.commands || 0;
                } catch (error) {
                    console.error('Ошибка загрузки статистики:', error);
                }
            }
            
            // Обновляем время
            function updateTime() {
                const now = new Date();
                document.getElementById('currentTime').textContent = 
                    now.toLocaleTimeString('ru-RU') + ' ' + now.toLocaleDateString('ru-RU');
            }
            
            // Обновляем статистику каждые 30 секунд
            loadStats();
            setInterval(loadStats, 30000);
            
            // Обновляем время каждую секунду
            setInterval(updateTime, 1000);
            updateTime();
        </script>
    </body>
    </html>
    """

@app.route('/health')
def health_check():
    """Проверка здоровья приложения для Render"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "telegram-analytics-bot",
        "version": "1.0.0"
    })

@app.route('/api/stats')
def api_stats():
    """API для получения статистики"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM posts")
        posts = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(views) FROM posts")
        views = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT COUNT(*) FROM commands_log")
        commands = cursor.fetchone()[0]
        
        conn.close()
        
        return jsonify({
            "status": "success",
            "data": {
                "users": users,
                "posts": posts,
                "views": views,
                "commands": commands,
                "timestamp": datetime.now().isoformat()
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    """Основной эндпоинт для вебхука Telegram"""
    if request.headers.get('content-type') == 'application/json':
        try:
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            return ''
        except Exception as e:
            logger.error(f"Ошибка обработки вебхука: {e}")
            return 'Error', 500
    return 'Bad request', 400

# ========== ЗАПУСК ПРИЛОЖЕНИЯ ==========
def start_bot_polling():
    """Запуск polling бота в отдельном потоке (как fallback)"""
    while True:
        try:
            logger.info("🔄 Запуск бота в режиме polling...")
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"❌ Ошибка в polling: {e}")
            time.sleep(5)

if __name__ == '__main__':
    # Инициализируем базу данных
    init_database()
    
    # Запускаем polling в отдельном потоке как fallback
    polling_thread = threading.Thread(target=start_bot_polling, daemon=True)
    polling_thread.start()
    
    # Запускаем Flask приложение
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Запуск Flask приложения на порту {port}")
    logger.info(f"🌐 Веб-приложение доступно по: http://localhost:{port}")
    logger.info(f"🤖 Бот токен: {'Установлен' if BOT_TOKEN else 'НЕ УСТАНОВЛЕН!'}")
    
    app.run(host='0.0.0.0', port=port, debug=False)
