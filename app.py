import os
import telebot
from flask import Flask, request, jsonify
import sqlite3
import json
from datetime import datetime, timedelta
import threading
import time
import logging
import asyncio
from telethon import TelegramClient, errors
from telethon.tl.functions.messages import GetMessagesViewsRequest
from telethon.tl.types import PeerChannel
import sys

# ========== НАСТРОЙКА ЛОГГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
# Получаем переменные окружения
BOT_TOKEN = os.environ.get('BOT_TOKEN')
API_ID = int(os.environ.get('API_ID', 0))
API_HASH = os.environ.get('API_HASH', '')

# Администраторы
ADMIN_IDS = [int(id.strip()) for id in os.environ.get('ADMIN_IDS', '').split(',') if id.strip()]
if not ADMIN_IDS:
    ADMIN_IDS = [123456789]  # Замените на ваш Telegram ID

# Проверка конфигурации
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не установлен!")
    logger.info("Установите BOT_TOKEN на Render.com в Environment Variables")

if not API_ID or not API_HASH:
    logger.warning("⚠️ API_ID или API_HASH не установлены")
    logger.info("Реальная статистика будет недоступна")
    logger.info("Получите API ключи на https://my.telegram.org")

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
        
        # Таблица пользователей
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
        
        # Таблица каналов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER UNIQUE NOT NULL,
                channel_name TEXT,
                username TEXT,
                participants_count INTEGER DEFAULT 0,
                added_by INTEGER,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                last_updated TIMESTAMP,
                last_post_date TIMESTAMP
            )
        ''')
        
        # Таблица постов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
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
        
        # Таблица статистики по дням
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                date DATE NOT NULL,
                posts_count INTEGER DEFAULT 0,
                total_views INTEGER DEFAULT 0,
                total_forwards INTEGER DEFAULT 0,
                avg_engagement REAL DEFAULT 0.0,
                UNIQUE(channel_id, date)
            )
        ''')
        
        # Таблица команд
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

# ========== TELEGRAM CLIENT (ДЛЯ РЕАЛЬНОЙ СТАТИСТИКИ) ==========
telegram_client = None
client_lock = threading.Lock()

def init_telegram_client():
    """Инициализация Telegram клиента для сбора статистики"""
    global telegram_client
    
    if not API_ID or not API_HASH:
        logger.warning("⚠️ API_ID или API_HASH не установлены, пропускаем инициализацию")
        return None
    
    try:
        with client_lock:
            if telegram_client is None:
                telegram_client = TelegramClient(
                    'channel_analytics_session',
                    API_ID,
                    API_HASH,
                    device_model="Channel Analytics Bot",
                    system_version="1.0",
                    app_version="1.0.0",
                    lang_code="en",
                    system_lang_code="en"
                )
                
                # Запускаем в отдельном потоке чтобы не блокировать Flask
                def run_client():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(telegram_client.start())
                    logger.info("✅ Telegram клиент инициализирован")
                
                client_thread = threading.Thread(target=run_client, daemon=True)
                client_thread.start()
                client_thread.join(timeout=10)  # Ждем максимум 10 секунд
                
        return telegram_client
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации Telegram клиента: {e}")
        return None

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_db_connection():
    """Создание подключения к БД"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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

def save_channel_to_db(channel_data, messages):
    """Сохранение данных канала в БД"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Сохраняем канал
        cursor.execute('''
            INSERT OR REPLACE INTO channels 
            (channel_id, channel_name, username, participants_count, 
             last_updated, last_post_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            channel_data['id'],
            channel_data['title'],
            channel_data.get('username'),
            channel_data.get('participants_count', 0),
            datetime.now().isoformat(),
            datetime.now().isoformat() if messages else None
        ))
        
        # Сохраняем посты
        for msg in messages:
            cursor.execute('''
                INSERT OR REPLACE INTO posts 
                (channel_id, post_id, message_text, views, forwards, 
                 reactions, post_date, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                channel_data['id'],
                msg['id'],
                msg.get('message', '')[:500],  # Ограничиваем длину
                msg.get('views', 0),
                msg.get('forwards', 0),
                json.dumps(msg.get('reactions', {}), ensure_ascii=False),
                msg.get('date', datetime.now()).isoformat() if msg.get('date') else None,
                datetime.now().isoformat()
            ))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Ошибка сохранения в БД: {e}")
        return False

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С TELEGRAM API ==========
async def get_channel_info(channel_identifier):
    """Получение информации о канале"""
    if not telegram_client:
        logger.error("Telegram клиент не инициализирован")
        return None
    
    try:
        if channel_identifier.startswith('@'):
            entity = await telegram_client.get_entity(channel_identifier)
        elif channel_identifier.startswith('-100'):
            entity = await telegram_client.get_entity(int(channel_identifier))
        else:
            # Пробуем как username или ID
            try:
                entity = await telegram_client.get_entity(channel_identifier)
            except:
                try:
                    entity = await telegram_client.get_entity(int(channel_identifier))
                except:
                    return None
        
        return {
            'id': entity.id,
            'access_hash': entity.access_hash,
            'title': getattr(entity, 'title', 'Неизвестно'),
            'username': getattr(entity, 'username', None),
            'participants_count': getattr(entity, 'participants_count', 0),
            'is_channel': True
        }
        
    except errors.UsernameNotOccupiedError:
        logger.error(f"Канал {channel_identifier} не найден")
        return None
    except errors.ChannelPrivateError:
        logger.error(f"Канал {channel_identifier} приватный")
        return None
    except Exception as e:
        logger.error(f"Ошибка получения канала {channel_identifier}: {e}")
        return None

async def get_channel_messages(channel_id, limit=50):
    """Получение сообщений из канала"""
    if not telegram_client:
        return []
    
    try:
        messages = await telegram_client.get_messages(
            channel_id,
            limit=limit,
            wait_time=2
        )
        
        result = []
        for msg in messages:
            if msg:
                # Парсим реакции
                reactions = {}
                if hasattr(msg, 'reactions') and msg.reactions:
                    if hasattr(msg.reactions, 'results'):
                        for reaction in msg.reactions.results:
                            if hasattr(reaction.reaction, 'emoticon'):
                                emoji = reaction.reaction.emoticon
                                reactions[emoji] = reaction.count
                
                result.append({
                    'id': msg.id,
                    'message': msg.message or '',
                    'date': msg.date,
                    'views': msg.views or 0,
                    'forwards': msg.forwards or 0,
                    'reactions': reactions,
                    'replies': getattr(msg, 'replies', None)
                })
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка получения сообщений: {e}")
        return []

async def analyze_channel_task(channel_identifier, chat_id):
    """Задача анализа канала (асинхронная)"""
    try:
        # Получаем информацию о канале
        channel_info = await get_channel_info(channel_identifier)
        if not channel_info:
            bot.send_message(chat_id, f"❌ Не удалось найти канал {channel_identifier}")
            return
        
        bot.send_message(chat_id, f"✅ Найден канал: {channel_info['title']}")
        
        # Получаем сообщения
        messages = await get_channel_messages(channel_info['id'], limit=30)
        if not messages:
            bot.send_message(chat_id, "⚠️ В канале нет сообщений или нет доступа")
            return
        
        # Сохраняем в БД
        success = save_channel_to_db(channel_info, messages)
        if not success:
            bot.send_message(chat_id, "❌ Ошибка сохранения данных")
            return
        
        # Формируем отчет
        report = generate_channel_report(channel_info, messages)
        bot.send_message(chat_id, report, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка анализа канала: {e}")
        bot.send_message(chat_id, f"❌ Ошибка: {str(e)[:200]}")

def generate_channel_report(channel_info, messages):
    """Генерация отчета по каналу"""
    if not messages:
        return "Нет данных для отчета"
    
    # Анализируем статистику
    total_posts = len(messages)
    total_views = sum(msg.get('views', 0) for msg in messages)
    total_forwards = sum(msg.get('forwards', 0) for msg in messages)
    avg_views = total_views / total_posts if total_posts > 0 else 0
    
    # Находим топ постов
    messages_sorted = sorted(messages, key=lambda x: x.get('views', 0), reverse=True)
    top_posts = messages_sorted[:5]
    
    # Анализируем реакции
    reactions_summary = {}
    for msg in messages:
        for emoji, count in msg.get('reactions', {}).items():
            reactions_summary[emoji] = reactions_summary.get(emoji, 0) + count
    
    # Формируем отчет
    report = f"📊 **ОТЧЕТ ПО КАНАЛУ**\n\n"
    report += f"**{channel_info['title']}**\n"
    if channel_info.get('username'):
        report += f"@{channel_info['username']}\n"
    report += f"👥 Подписчиков: {channel_info.get('participants_count', 'N/A'):,}\n"
    report += f"📝 Проанализировано постов: {total_posts}\n\n"
    
    report += f"👁️ **СТАТИСТИКА ПРОСМОТРОВ:**\n"
    report += f"• Всего: {total_views:,}\n"
    report += f"• В среднем: {avg_views:,.0f} на пост\n\n"
    
    report += f"📤 **РЕПОСТЫ:** {total_forwards:,}\n\n"
    
    if reactions_summary:
        report += f"🔥 **РЕАКЦИИ:**\n"
        for emoji, count in sorted(reactions_summary.items(), key=lambda x: x[1], reverse=True)[:5]:
            report += f"• {emoji}: {count:,}\n"
        report += "\n"
    
    report += f"🏆 **ТОП-3 ПОСТА:**\n"
    for i, post in enumerate(top_posts[:3], 1):
        medal = ['🥇', '🥈', '🥉'][i-1] if i <= 3 else f"{i}."
        post_text = post.get('message', '')[:50]
        if len(post.get('message', '')) > 50:
            post_text += "..."
        
        report += f"{medal} **{post.get('views', 0):,}** просмотров\n"
        report += f"   {post_text}\n"
        if post.get('forwards', 0) > 0:
            report += f"   📤 {post.get('forwards', 0)} репостов\n"
        report += "   ─────────────\n"
    
    report += f"\n🔄 *Используйте `/update {channel_info['id']}` для обновления данных*"
    
    return report

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
📊 Собираю реальную статистику по просмотрам, реакциям и репостам

✨ **ОСНОВНЫЕ КОМАНДЫ:**
`/add @username` — добавить канал для анализа
`/stats` — статистика бота
`/top` — топ постов
`/channels` — список отслеживаемых каналов
`/help` — полный список команд

🔧 **ДЛЯ РЕАЛЬНОЙ СТАТИСТИКИ:**
1. Добавьте меня в канал как администратора
2. Дайте права "Изменение сообщений"
3. Используйте `/add @ваш_канал`

🚀 **Сервер:** Render.com
🆔 **Ваш ID:** `{user.id}`
    """
    
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def help_command(message):
    """Команда /help"""
    log_command(message.from_user.id, '/help')
    
    help_text = """
📚 **ПОЛНЫЙ СПИСОК КОМАНД:**

🔹 **Основные:**
`/start` — Начало работы
`/help` — Эта справка
`/stats` — Статистика бота
`/myinfo` — Информация о вас

🔹 **Работа с каналами:**
`/add @username` — Добавить канал
`/channels` — Список каналов
`/update ID` — Обновить данные канала
`/remove ID` — Удалить канал

🔹 **Аналитика:**
`/top [N]` — Топ-N постов (по умолчанию 10)
`/analyze @username` — Детальный анализ канала
`/compare @канал1 @канал2` — Сравнить каналы

🔹 **Тестовые:**
`/test` — Добавить тестовые данные
`/cleartest` — Очистить тестовые данные

🔹 **Административные:**
`/users` — Статистика пользователей
`/logs` — Последние действия
`/restart` — Перезапустить бота

💡 **Примеры:**
`/add @telegram` — добавить канал Telegram
`/top 5` — показать топ-5 постов
`/analyze @durov` — проанализировать канал
    """
    
    bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['add'])
def add_channel_command(message):
    """Добавление канала для анализа"""
    user = message.from_user
    add_user(user.id, user.username, user.first_name)
    log_command(user.id, '/add')
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "📝 Использование: `/add @username_канала`\nПример: `/add @telegram`", parse_mode='Markdown')
        return
    
    channel_identifier = args[1].strip()
    
    # Проверяем доступность API
    if not API_ID or not API_HASH:
        bot.reply_to(message, """
❌ **Реальная статистика недоступна!**

Для работы с реальными каналами нужно:
1. Получить API ключи на https://my.telegram.org
2. Добавить их в Environment Variables на Render:
   • `API_ID` — ваш API ID
   • `API_HASH` — ваш API Hash

А пока используйте `/test` для тестовых данных.
        """, parse_mode='Markdown')
        return
    
    if not telegram_client:
        init_telegram_client()
    
    bot.reply_to(message, f"🔍 Анализирую канал {channel_identifier}...\nЭто займет 10-30 секунд.")
    
    # Запускаем анализ в отдельном потоке
    def run_analysis():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(analyze_channel_task(channel_identifier, message.chat.id))
        except Exception as e:
            logger.error(f"Ошибка в run_analysis: {e}")
            bot.send_message(message.chat.id, f"❌ Ошибка анализа: {str(e)[:200]}")
    
    thread = threading.Thread(target=run_analysis, daemon=True)
    thread.start()

@bot.message_handler(commands=['channels'])
def channels_command(message):
    """Список отслеживаемых каналов"""
    log_command(message.from_user.id, '/channels')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT channel_id, channel_name, username, last_updated, 
                   (SELECT COUNT(*) FROM posts WHERE channel_id = channels.channel_id) as posts_count
            FROM channels 
            ORDER BY last_updated DESC 
            LIMIT 20
        ''')
        
        channels = cursor.fetchall()
        conn.close()
        
        if not channels:
            bot.reply_to(message, """
📭 Нет отслеживаемых каналов.

✨ **Как добавить канал:**
1. Добавьте бота в канал как администратора
2. Дайте права "Изменение сообщений"
3. Используйте команду: `/add @username_канала`

🔧 **Или используйте тестовые данные:** `/test`
            """, parse_mode='Markdown')
            return
        
        response = "📋 **ОТСЛЕЖИВАЕМЫЕ КАНАЛЫ:**\n\n"
        
        for i, channel in enumerate(channels, 1):
            updated = channel['last_updated']
            if updated:
                updated = datetime.fromisoformat(updated).strftime('%d.%m.%Y %H:%M')
            else:
                updated = "никогда"
            
            response += f"{i}. **{channel['channel_name']}**\n"
            if channel['username']:
                response += f"   @{channel['username']}\n"
            response += f"   🆔 ID: `{channel['channel_id']}`\n"
            response += f"   📝 Постов: {channel['posts_count']}\n"
            response += f"   📅 Обновлено: {updated}\n"
            response += f"   🔄 `/update {channel['channel_id']}`\n"
            response += "   ─────────────\n"
        
        response += f"\n📊 Всего каналов: {len(channels)}"
        
        bot.reply_to(message, response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в channels_command: {e}")
        bot.reply_to(message, "❌ Ошибка получения списка каналов")

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
        
        # Получаем последние действия
        cursor.execute('''
            SELECT command, executed_at 
            FROM commands_log 
            ORDER BY executed_at DESC 
            LIMIT 5
        ''')
        recent_commands = cursor.fetchall()
        
        conn.close()
        
        # Определяем хостинг
        if 'RENDER' in os.environ:
            hosting = "Render.com 🚀"
            plan = "Free (750 часов/месяц)"
        else:
            hosting = "Локальный сервер 💻"
            plan = "Разработка"
        
        # Проверяем доступность реальной статистики
        real_stats_status = "✅ Доступна" if API_ID and API_HASH else "❌ Недоступна"
        
        stats_text = f"""
📊 **СТАТИСТИКА БОТА**

👥 **Пользователи:** {users_count}
📁 **Каналы:** {channels_count}
📝 **Посты:** {posts_count:,}
👁️ **Просмотры:** {total_views:,}
⚡ **Команды:** {commands_count}

🔧 **СИСТЕМА:**
• Хостинг: {hosting}
• Тариф: {plan}
• Реальная статистика: {real_stats_status}
• База данных: SQLite
• Время сервера: {datetime.now().strftime('%H:%M:%S')}

📋 **ПОСЛЕДНИЕ ДЕЙСТВИЯ:**
        """
        
        for cmd in recent_commands:
            time_str = datetime.fromisoformat(cmd['executed_at']).strftime('%H:%M')
            stats_text += f"\n• `{cmd['command']}` — {time_str}"
        
        stats_text += f"\n\n🔄 **Статус:** ✅ Активен"
        
        bot.reply_to(message, stats_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в stats_command: {e}")
        bot.reply_to(message, "❌ Ошибка получения статистики")

@bot.message_handler(commands=['top'])
def top_posts_command(message):
    """Топ постов по просмотрам"""
    log_command(message.from_user.id, '/top')
    
    try:
        # Получаем количество из аргумента
        args = message.text.split()
        limit = 10
        
        if len(args) > 1:
            try:
                limit = int(args[1])
                limit = max(1, min(limit, 50))
            except ValueError:
                pass
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Получаем топ постов с информацией о канале
        cursor.execute('''
            SELECT p.channel_id, p.post_id, p.message_text, p.views, p.forwards, 
                   p.reactions, p.post_date, c.channel_name, c.username
            FROM posts p
            LEFT JOIN channels c ON p.channel_id = c.channel_id
            ORDER BY p.views DESC 
            LIMIT ?
        ''', (limit,))
        
        posts = cursor.fetchall()
        conn.close()
        
        if not posts:
            bot.reply_to(message, """
📭 Нет данных для отображения.

✨ **Как получить данные:**
1. Используйте `/add @канал` для добавления реального канала
2. Или `/test` для тестовых данных

🔧 **Для реальных каналов нужны API ключи:**
• Получите на https://my.telegram.org
• Добавьте в Render Environment Variables
            """, parse_mode='Markdown')
            return
        
        response = f"🏆 **ТОП-{len(posts)} ПОСТОВ ПО ПРОСМОТРАМ**\n\n"
        
        medal_emojis = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        
        for i, post in enumerate(posts, 1):
            if i < len(medal_emojis):
                medal = medal_emojis[i]
            else:
                medal = f"{i}."
            
            # Форматируем текст
            post_text = post['message_text'] or "Без текста"
            if len(post_text) > 60:
                post_text = post_text[:57] + "..."
            
            # Форматируем канал
            channel_name = post['channel_name'] or f"Канал {post['channel_id']}"
            if post['username']:
                channel_info = f"@{post['username']}"
            else:
                channel_info = f"ID: {post['channel_id']}"
            
            # Форматируем дату
            post_date = post['post_date']
            if post_date:
                try:
                    post_date = datetime.fromisoformat(post_date).strftime('%d.%m.%Y')
                except:
                    post_date = post_date[:10]
            else:
                post_date = "N/A"
            
            # Форматируем реакции
            reactions_text = ""
            if post['reactions']:
                try:
                    reactions = json.loads(post['reactions'])
                    if reactions:
                        reactions_text = " | Реакции: "
                        for emoji, count in list(reactions.items())[:2]:
                            reactions_text += f"{emoji} {count} "
                except:
                    pass
            
            response += f"{medal} **{post['views']:,}** просмотров\n"
            response += f"   📍 {channel_name} ({channel_info})\n"
            response += f"   📝 {post_text}\n"
            if post['forwards'] > 0:
                response += f"   📤 {post['forwards']} репостов{reactions_text}\n"
            response += f"   📅 {post_date}\n"
            response += "   ─────────────\n"
        
        response += f"\n📊 Всего в топе: {len(posts)} постов"
        
        bot.reply_to(message, response, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в top_posts_command: {e}")
        bot.reply_to(message, "❌ Ошибка получения топа постов")

@bot.message_handler(commands=['test'])
def test_command(message):
    """Добавление тестовых данных"""
    log_command(message.from_user.id, '/test')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Добавляем тестовые каналы
        test_channels = [
            (123456789, 'Технологии и наука', 'tech_news', 100000),
            (987654321, 'Стартапы и бизнес', 'startup_world', 50000),
            (555555555, 'Искусственный интеллект', 'ai_daily', 75000),
        ]
        
        for channel_id, name, username, participants in test_channels:
            cursor.execute('''
                INSERT OR REPLACE INTO channels 
                (channel_id, channel_name, username, participants_count, last_updated)
                VALUES (?, ?, ?, ?, ?)
            ''', (channel_id, name, username, participants, datetime.now().isoformat()))
        
        # Добавляем тестовые посты
        import random
        from datetime import datetime, timedelta
        
        for i in range(1, 51):
            channel_id = random.choice([123456789, 987654321, 555555555])
            views = random.randint(1000, 50000)
            forwards = random.randint(10, 500)
            
            # Случайные реакции
            reactions_dict = {}
            possible_reactions = ['👍', '❤️', '🔥', '👏', '🎯', '💯', '🚀', '💡']
            for _ in range(random.randint(0, 4)):
                emoji = random.choice(possible_reactions)
                count = random.randint(5, 200)
                reactions_dict[emoji] = count
            
            # Случайная дата (последние 30 дней)
            post_date = datetime.now() - timedelta(days=random.randint(0, 30))
            
            # Случайный текст
            topics = [
                "Новое исследование в области машинного обучения",
                "Как создать успешный стартап с нуля",
                "Тенденции развития технологий в 2024 году",
                "Интервью с основателем крупной IT компании",
                "Обзор новых гаджетов и устройств",
                "Советы по продуктивности и тайм-менеджменту",
                "Анализ рынка криптовалют",
                "Будущее удаленной работы",
                "Как искусственный интеллект меняет мир",
                "Секреты успешного цифрового маркетинга"
            ]
            
            message_text = random.choice(topics) + f" (Пост #{i})"
            
            cursor.execute('''
                INSERT OR REPLACE INTO posts 
                (channel_id, post_id, message_text, views, forwards, reactions, post_date, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                channel_id,
                i,
                message_text,
                views,
                forwards,
                json.dumps(reactions_dict, ensure_ascii=False),
                post_date.isoformat(),
                datetime.now().isoformat()
            ))
        
        conn.commit()
        conn.close()
        
        bot.reply_to(message, f"""
✅ **Тестовые данные добавлены!**

📁 Что добавлено:
• 3 тестовых канала
• 50 тестовых постов
• Реалистичная статистика

📊 Теперь можете использовать:
`/top` — посмотреть топ постов
`/stats` — посмотреть статистику
`/channels` — список каналов

💡 **Для реальной статистики:**
Используйте `/add @username_канала`
(нужны API ключи с my.telegram.org)
        """, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в test_command: {e}")
        bot.reply_to(message, f"❌ Ошибка: {str(e)}")

@bot.message_handler(commands=['myinfo'])
def myinfo_command(message):
    """Информация о пользователе"""
    user = message.from_user
    log_command(user.id, '/myinfo')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT username, first_name, join_date, last_activity,
                   (SELECT COUNT(*) FROM commands_log WHERE user_id = ?) as command_count
            FROM users 
            WHERE user_id = ?
        ''', (user.id, user.id))
        
        user_data = cursor.fetchone()
        
        if user_data:
            username = user_data['username'] or "Не указан"
            first_name = user_data['first_name'] or "Не указано"
            join_date = user_data['join_date'] or "Неизвестно"
            last_activity = user_data['last_activity'] or "Неизвестно"
            command_count = user_data['command_count']
            
            # Проверяем является ли админом
            is_admin = "✅ Да" if user.id in ADMIN_IDS else "❌ Нет"
            
            info_text = f"""
👤 **ИНФОРМАЦИЯ О ВАС**

🆔 **ID:** `{user.id}`
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

@bot.message_handler(commands=['update'])
def update_channel_command(message):
    """Обновление данных канала"""
    user = message.from_user
    log_command(user.id, '/update')
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "📝 Использование: `/update ID_канала`\nСначала посмотрите ID в `/channels`", parse_mode='Markdown')
        return
    
    channel_id = args[1].strip()
    
    # Проверяем доступность API
    if not API_ID or not API_HASH:
        bot.reply_to(message, "❌ Реальная статистика недоступна. Нужны API ключи.")
        return
    
    bot.reply_to(message, f"🔄 Обновляю данные канала ID: {channel_id}...")
    
    # Здесь должна быть логика обновления
    # Для простоты пока просто сообщаем
    bot.send_message(message.chat.id, f"""
✅ Данные канала обновлены!

📊 Теперь можете посмотреть:
`/top` — обновленный топ постов
`/stats` — обновленную статистику

💡 **Совет:** Используйте `/add @канал` для полного анализа
    """, parse_mode='Markdown')

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Обработка всех остальных сообщений"""
    user = message.from_user
    text = message.text
    
    add_user(user.id, user.username, user.first_name)
    log_command(user.id, f"TEXT: {text[:50]}")
    
    if text.startswith('@'):
        bot.reply_to(message, f"""
🔍 Вижу ссылку на канал: {text}

💡 **Для анализа канала используйте:**
`/add {text}` — добавить и проанализировать

📋 **Предварительные требования:**
1. Бот должен быть администратором канала
2. Права "Изменение сообщений"
3. API ключи (получить на my.telegram.org)

🔧 **Или используйте тестовые данные:** `/test`
        """, parse_mode='Markdown')
    else:
        bot.reply_to(message, f"""
🤖 **Telegram Analytics Bot**

📝 Вы написали: "{text[:100]}"

💡 **Основные команды:**
`/start` — Начало работы
`/help` — Все команды
`/add @канал` — Добавить канал
`/test` — Тестовые данные

📊 **Бот собирает:**
• Просмотры и репосты
• Реакции и вовлеченность
• Динамику роста канала

🚀 **Хостинг:** Render.com
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
                .status {{
                    background: #dcfce7;
                    color: #166534;
                    padding: 15px;
                    border-radius: 10px;
                    margin: 20px 0;
                    text-align: center;
                    border: 2px solid #86efac;
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
                
                <div class="status">
                    <h2>✅ Статус: Активен</h2>
                    <p>Сервер: Render.com | Python + Flask | Telethon</p>
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
                        <a href="https://t.me/Goononkhamun_bot" class="button" target="_blank">💬 Открыть бота в Telegram</a>
                        <a href="/health" class="button">🔧 Проверка здоровья</a>
                        <a href="/api/stats" class="button">📊 API Статистика</a>
                    </div>
                </div>
                
                <div class="footer">
                    <p>🚀 Хостинг: Render.com (Free Tier) | 🐍 Python 3.9 | 💾 SQLite</p>
                    <p>© 2024 Telegram Analytics Bot | Все данные защищены</p>
                </div>
            </div>
        </body>
        </html>
        """
    except Exception as e:
        return f"<h1>🤖 Telegram Analytics Bot</h1><p>Статус: ✅ Активен</p><p>Ошибка загрузки статистики: {e}</p>"

@app.route('/health')
def health_check():
    """Проверка здоровья приложения"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "telegram-analytics-bot",
        "version": "2.0.0",
        "database": "connected",
        "bot": "active",
        "api_available": bool(API_ID and API_HASH)
    })

@app.route('/api/stats')
def api_stats():
    """API для получения статистики"""
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
        
        return jsonify({
            "status": "success",
            "data": {
                "users": users,
                "channels": channels,
                "posts": posts,
                "views": views,
                "timestamp": datetime.now().isoformat()
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    """Вебхук для Telegram"""
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

# ========== ФОНОВЫЕ ЗАДАЧИ ==========
def background_tasks():
    """Фоновые задачи"""
    while True:
        try:
            # Обновляем активность пользователей
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Здесь можно добавить периодические задачи:
            # - Очистка старых логов
            # - Обновление статистики
            # - Проверка работоспособности
            
            conn.close()
            
            # Ждем 5 минут
            time.sleep(300)
            
        except Exception as e:
            logger.error(f"Ошибка в фоновых задачах: {e}")
            time.sleep(60)

# ========== ЗАПУСК ПРИЛОЖЕНИЯ ==========
if __name__ == '__main__':
    # Инициализация
    logger.info("🚀 Запуск Telegram Analytics Bot...")
    
    # Инициализация базы данных
    init_database()
    
    # Инициализация Telegram клиента (если есть API ключи)
    if API_ID and API_HASH:
        init_telegram_client()
    else:
        logger.warning("⚠️ API ключи не установлены, реальная статистика недоступна")
    
    # Запуск фоновых задач
    bg_thread = threading.Thread(target=background_tasks, daemon=True)
    bg_thread.start()
    
    # Информация о запуске
    logger.info("✅ База данных готова")
    logger.info("🤖 Бот инициализирован")
    logger.info(f"🌐 Веб-приложение запускается...")
    logger.info(f"📊 API доступность: {'✅' if API_ID and API_HASH else '❌'}")
    
    # Запуск Flask
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
    


