import sys
print("=" * 50)
print("🚀 Начало выполнения app.py")
print(f"Python версия: {sys.version}")
print(f"Аргументы: {sys.argv}")
print("=" * 50)

# Проверяем импорты
try:
    from flask import Flask
    print("✅ Flask импортирован")
except ImportError as e:
    print(f"❌ Ошибка импорта Flask: {e}")
    sys.exit(1)

try:
    import telebot
    print("✅ telebot импортирован")
except ImportError as e:
    print(f"❌ Ошибка импорта telebot: {e}")
    sys.exit(1)

# ... остальной код ...

import os
import telebot
from flask import Flask, request, jsonify
import sqlite3
import json
from datetime import datetime, timedelta
import threading
import time
import logging
import random

# ========== НАСТРОЙКА ЛОГГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не установлен!")
    # Для теста можно временно указать здесь
    # BOT_TOKEN = "ваш_токен"

ADMIN_IDS = [int(id.strip()) for id in os.environ.get('ADMIN_IDS', '').split(',') if id.strip()]
if not ADMIN_IDS:
    ADMIN_IDS = [123456789]  # ЗАМЕНИТЕ НА ВАШ ID

# Динамическая ссылка на бота
BOT_USERNAME = os.environ.get('BOT_USERNAME', 'your_bot_username')
BOT_LINK = f"https://t.me/{BOT_USERNAME}"

# Инициализация бота и Flask
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ========== БАЗА ДАННЫХ ==========
DB_PATH = '/tmp/bot_database.db' if 'RENDER' in os.environ else 'bot_database.db'

def init_database():
    """Инициализация базы данных"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE NOT NULL,
                channel_name TEXT,
                username TEXT,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        ''')
        
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
        logger.info(f"✅ База данных инициализирована")
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def add_user(user_id, username, first_name):
    """Добавление пользователя в БД"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, last_activity)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, first_name, datetime.now()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка добавления пользователя: {e}")

def log_command(user_id, command):
    """Логирование команд"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO commands_log (user_id, command) VALUES (?, ?)",
            (user_id, command)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка логирования: {e}")

# ========== КОМАНДЫ БОТА ==========
@bot.message_handler(commands=['start'])
def start_command(message):
    """Команда /start"""
    user = message.from_user
    add_user(user.id, user.username, user.first_name)
    log_command(user.id, '/start')
    
    welcome_text = f"""
👋 Привет, {user.first_name}!

🤖 **Я — бот для анализа Telegram-каналов**

✨ **ОСНОВНЫЕ КОМАНДЫ:**
`/stats` — статистика бота
`/top` — топ постов
`/channels` — список каналов
`/test` — тестовые данные
`/help` — все команды

🚀 **Хостинг:** Render.com
🔗 **Ссылка:** {BOT_LINK}
🆔 **Ваш ID:** `{user.id}`
    """
    
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def help_command(message):
    """Команда /help"""
    log_command(message.from_user.id, '/help')
    
    help_text = f"""
📚 **ПОЛНЫЙ СПИСОК КОМАНД:**

🔹 **Основные:**
`/start` — Начало работы
`/help` — Эта справка
`/stats` — Статистика
`/myinfo` — Информация о вас

🔹 **Аналитика:**
`/top [N]` — Топ-N постов
`/channels` — Список каналов

🔹 **Тестовые:**
`/test` — Добавить тестовые данные

🔹 **Информация:**
`/about` — О боте
`/status` — Статус сервера

🔗 **Ссылка:** {BOT_LINK}
🌐 **Сервер:** Render.com
    """
    
    bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['stats'])
def stats_command(message):
    """Статистика бота"""
    log_command(message.from_user.id, '/stats')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM channels")
        channels = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM posts")
        posts = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(views) FROM posts")
        views = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT COUNT(*) FROM commands_log")
        commands = cursor.fetchone()[0]
        
        conn.close()
        
        stats_text = f"""
📊 **СТАТИСТИКА БОТА**

👥 Пользователей: {users}
📁 Каналов: {channels}
📝 Постов: {posts:,}
👁️ Просмотров: {views:,}
⚡ Команд: {commands}

🌐 **СЕРВЕР:**
• Хостинг: Render.com
• Статус: ✅ Активен
• Время: {datetime.now().strftime('%H:%M:%S')}

🔗 **Ссылка:** {BOT_LINK}
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
        args = message.text.split()
        limit = 10
        
        if len(args) > 1:
            try:
                limit = int(args[1])
                limit = max(1, min(limit, 20))
            except:
                pass
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT p.channel_id, p.message_text, p.views, p.forwards, 
                   p.reactions, c.channel_name
            FROM posts p
            LEFT JOIN channels c ON p.channel_id = c.channel_id
            ORDER BY p.views DESC 
            LIMIT ?
        ''', (limit,))
        
        posts = cursor.fetchall()
        conn.close()
        
        if not posts:
            bot.reply_to(message, "📭 Нет данных. Используйте `/test`", parse_mode='Markdown')
            return
        
        response = f"🏆 **ТОП-{len(posts)} ПОСТОВ**\n\n"
        
        for i, post in enumerate(posts, 1):
            medal = ['🥇', '🥈', '🥉'][i-1] if i <= 3 else f"{i}."
            
            text = post['message_text'] or "Без текста"
            if len(text) > 50:
                text = text[:47] + "..."
            
            channel = post['channel_name'] or post['channel_id']
            
            response += f"{medal} **{post['views']:,}** просмотров\n"
            response += f"   📍 {channel}\n"
            response += f"   📝 {text}\n"
            if post['forwards'] > 0:
                response += f"   📤 {post['forwards']} репостов\n"
            response += "   ─────────────\n"
        
        response += f"\n📊 Всего в топе: {len(posts)} постов"
        
        bot.reply_to(message, response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в top_posts_command: {e}")
        bot.reply_to(message, "❌ Ошибка получения топа")

@bot.message_handler(commands=['test'])
def test_command(message):
    """Добавление тестовых данных"""
    log_command(message.from_user.id, '/test')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Тестовые каналы
        test_channels = [
            ('@tech_news', 'Новости технологий'),
            ('@startup_world', 'Мир стартапов'),
            ('@ai_daily', 'ИИ сегодня'),
        ]
        
        for username, name in test_channels:
            cursor.execute('''
                INSERT OR IGNORE INTO channels (channel_id, channel_name, username)
                VALUES (?, ?, ?)
            ''', (username, name, username[1:]))
        
        # Тестовые посты
        topics = [
            "Новое исследование в области машинного обучения",
            "Стартап привлек $10M инвестиций",
            "Искусственный интеллект в медицине",
            "Технологии будущего в 2024 году",
            "Как создать успешный продукт",
            "Цифровая трансформация бизнеса",
            "Тенденции развития ИИ",
            "Кибербезопасность в современном мире",
            "Облачные технологии",
            "Мобильная разработка: тренды"
        ]
        
        for i in range(1, 31):
            channel = random.choice(test_channels)[0]
            views = random.randint(1000, 50000)
            forwards = random.randint(5, 300)
            
            reactions = {}
            if random.random() > 0.3:
                for emoji in ['👍', '❤️', '🔥', '🎯']:
                    if random.random() > 0.5:
                        reactions[emoji] = random.randint(10, 200)
            
            cursor.execute('''
                INSERT OR REPLACE INTO posts 
                (channel_id, post_id, message_text, views, forwards, reactions, post_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                channel,
                i,
                f"{random.choice(topics)} (Пост #{i})",
                views,
                forwards,
                json.dumps(reactions),
                (datetime.now() - timedelta(days=random.randint(0, 30))).isoformat()
            ))
        
        conn.commit()
        conn.close()
        
        bot.reply_to(message, f"""
✅ **Тестовые данные добавлены!**

📁 Добавлено:
• 3 тестовых канала
• 30 тестовых постов

📊 Теперь можете:
`/top` — посмотреть топ постов
`/stats` — общую статистику
`/channels` — список каналов
        """, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в test_command: {e}")
        bot.reply_to(message, f"❌ Ошибка: {str(e)}")

@bot.message_handler(commands=['channels'])
def channels_command(message):
    """Список каналов"""
    log_command(message.from_user.id, '/channels')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT channel_name, username, added_date,
                   (SELECT COUNT(*) FROM posts WHERE channel_id = channels.channel_id) as posts_count
            FROM channels 
            ORDER BY added_date DESC 
            LIMIT 10
        ''')
        
        channels = cursor.fetchall()
        conn.close()
        
        if not channels:
            bot.reply_to(message, "📭 Нет каналов. Используйте `/test`", parse_mode='Markdown')
            return
        
        response = "📋 **СПИСОК КАНАЛОВ**\n\n"
        
        for i, channel in enumerate(channels, 1):
            response += f"{i}. **{channel['channel_name']}**\n"
            if channel['username']:
                response += f"   @{channel['username']}\n"
            response += f"   📝 Постов: {channel['posts_count']}\n"
            response += f"   📅 Добавлен: {channel['added_date'][:10]}\n"
            response += "   ─────────────\n"
        
        response += f"\n📊 Всего каналов: {len(channels)}"
        
        bot.reply_to(message, response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в channels_command: {e}")
        bot.reply_to(message, "❌ Ошибка получения списка")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Обработка всех сообщений"""
    user = message.from_user
    text = message.text
    
    add_user(user.id, user.username, user.first_name)
    log_command(user.id, f"TEXT: {text[:30]}")
    
    bot.reply_to(message, f"""
🤖 **Telegram Analytics Bot**

📝 Вы написали: "{text[:50]}"

💡 **Основные команды:**
`/start` — начало работы
`/help` — все команды
`/test` — тестовые данные
`/stats` — статистика

🔗 **Ссылка:** {BOT_LINK}
    """, parse_mode='Markdown')

# ========== FLASK МАРШРУТЫ ==========
@app.route('/')
def home():
    """Главная страница"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM channels")
        channels = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM posts")
        posts = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(views) FROM posts")
        views = cursor.fetchone()[0] or 0
        
        conn.close()
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Telegram Analytics Bot</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    color: white;
                }}
                .container {{
                    background: rgba(255, 255, 255, 0.95);
                    color: #333;
                    padding: 40px;
                    border-radius: 20px;
                    box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                }}
                h1 {{
                    color: #4f46e5;
                    text-align: center;
                    font-size: 2.5rem;
                }}
                .stats {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 20px;
                    margin: 40px 0;
                }}
                .stat-card {{
                    background: #f8fafc;
                    padding: 20px;
                    border-radius: 10px;
                    text-align: center;
                    border: 2px solid #e2e8f0;
                }}
                .stat-card h3 {{
                    color: #64748b;
                    margin: 0 0 10px 0;
                }}
                .stat-card .value {{
                    font-size: 2rem;
                    font-weight: bold;
                    color: #1e293b;
                }}
                .button {{
                    display: inline-block;
                    background: #4f46e5;
                    color: white;
                    padding: 15px 30px;
                    text-decoration: none;
                    border-radius: 10px;
                    margin: 10px;
                    font-weight: bold;
                    transition: transform 0.3s;
                }}
                .button:hover {{
                    transform: translateY(-2px);
                    background: #4338ca;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 40px;
                    color: #64748b;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🤖 Telegram Analytics Bot</h1>
                
                <div style="text-align: center; margin: 20px 0; padding: 15px; background: #dcfce7; border-radius: 10px; color: #166534;">
                    <h2 style="margin: 0;">✅ Статус: Активен</h2>
                    <p style="margin: 5px 0;">Username: @{BOT_USERNAME} | Сервер: Render.com</p>
                </div>
                
                <div class="stats">
                    <div class="stat-card">
                        <h3>👥 Пользователи</h3>
                        <div class="value">{users}</div>
                    </div>
                    <div class="stat-card">
                        <h3>📁 Каналы</h3>
                        <div class="value">{channels}</div>
                    </div>
                    <div class="stat-card">
                        <h3>📝 Посты</h3>
                        <div class="value">{posts}</div>
                    </div>
                    <div class="stat-card">
                        <h3>👁️ Просмотры</h3>
                        <div class="value">{views:,}</div>
                    </div>
                </div>
                
                <div style="text-align: center; margin: 40px 0;">
                    <h2>✨ Аналитика Telegram-каналов</h2>
                    <p>Сбор статистики по просмотрам, реакциям, репостам</p>
                    
                    <div style="margin: 30px 0;">
                        <a href="{BOT_LINK}" class="button" target="_blank">💬 Открыть @{BOT_USERNAME}</a>
                        <a href="/health" class="button">🔧 Проверка здоровья</a>
                        <a href="/api/stats" class="button">📊 API Статистика</a>
                    </div>
                </div>
                
                <div class="footer">
                    <p>🚀 Хостинг: Render.com (Free Tier) | 🐍 Python 3.9 | 💾 SQLite</p>
                    <p>© 2024 Telegram Analytics Bot</p>
                </div>
            </div>
        </body>
        </html>
        """
    except Exception as e:
        return f"""
        <!DOCTYPE html>
        <html>
        <head><title>Telegram Analytics Bot</title></head>
        <body style="font-family: Arial; padding: 20px;">
            <h1>🤖 Telegram Analytics Bot</h1>
            <p>✅ Статус: Активен</p>
            <p>🔗 Ссылка: <a href="{BOT_LINK}">{BOT_LINK}</a></p>
            <a href="{BOT_LINK}" style="background: #4f46e5; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
                💬 Открыть бота
            </a>
        </body>
        </html>
        """

@app.route('/health')
def health_check():
    """Проверка здоровья"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "bot_username": BOT_USERNAME,
        "bot_link": BOT_LINK,
        "server": "Render.com",
        "webhook": "active"
    })

@app.route('/api/stats')
def api_stats():
    """API статистики"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM channels")
        channels = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM posts")
        posts = cursor.fetchone()[0]
        
        conn.close()
        
        return jsonify({
            "status": "success",
            "bot_username": BOT_USERNAME,
            "bot_link": BOT_LINK,
            "stats": {
                "users": users,
                "channels": channels,
                "posts": posts
            }
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "bot_username": BOT_USERNAME,
            "error": str(e)
        }), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    """Вебхук Telegram"""
    if request.headers.get('content-type') == 'application/json':
        try:
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            return ''
        except Exception as e:
            logger.error(f"Ошибка вебхука: {e}")
            return 'Error', 500
    return 'Bad request', 400

# ========== ЗАПУСК ==========
if __name__ == '__main__':
    logger.info("🚀 Запуск Telegram Analytics Bot...")
    
    # Инициализация БД
    init_database()
    
    logger.info("✅ Бот: @{Goononkhamun_bot}")
    logger.info(f"🔗 Ссылка: {BOT_LINK}")
    logger.info("🌐 Веб-приложение запускается...")
    logger.info("📡 Режим: Вебхук (без polling)")
    
    # Запуск Flask
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)


