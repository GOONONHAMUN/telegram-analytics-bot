import os
import telebot
from flask import Flask, request, jsonify
import sqlite3
import json
from datetime import datetime
import threading
import time
import logging
import asyncio
from channel_monitor import ChannelMonitor
from config import Config

# ========== НАСТРОЙКА ЛОГГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
Config.validate()
BOT_TOKEN = Config.BOT_TOKEN
ADMIN_IDS = Config.ADMIN_IDS

# Инициализация бота и Flask
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Инициализация монитора каналов
channel_monitor = None

def init_channel_monitor():
    """Инициализация монитора каналов"""
    global channel_monitor
    if Config.API_ID and Config.API_HASH:
        try:
            # Запускаем в отдельном потоке
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            channel_monitor = ChannelMonitor(
                api_id=Config.API_ID,
                api_hash=Config.API_HASH
            )
            
            # Запускаем подключение асинхронно
            def run_connect():
                asyncio.run(channel_monitor.connect())
            
            thread = threading.Thread(target=run_connect, daemon=True)
            thread.start()
            
            logger.info("✅ Монитор каналов инициализирован")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации монитора каналов: {e}")
            return False
    else:
        logger.warning("⚠️ API_ID и API_HASH не установлены, реальная статистика недоступна")
        return False

# ========== БАЗА ДАННЫХ ==========
DB_PATH = Config.DB_PATH

def init_database():
    """Инициализация базы данных с расширенными таблицами"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Существующие таблицы
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
        
        # Расширенная таблица каналов
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
                FOREIGN KEY (added_by) REFERENCES users (user_id)
            )
        ''')
        
        # Расширенная таблица постов
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
        
        # Таблица для хранения статистики по дням
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

# ========== НОВЫЕ КОМАНДЫ ДЛЯ РЕАЛЬНОЙ СТАТИСТИКИ ==========
@bot.message_handler(commands=['add_channel'])
def add_channel_command(message):
    """Добавление канала для мониторинга"""
    user_id = message.from_user.id
    add_user(user_id, message.from_user.username, message.from_user.first_name)
    
    # Проверяем права
    if user_id not in ADMIN_IDS:
        bot.reply_to(message, "❌ Эта команда доступна только администраторам.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "📝 Использование: `/add_channel @username_канала`", parse_mode='Markdown')
        return
    
    channel_identifier = args[1].strip()
    
    # Проверяем формат
    if not (channel_identifier.startswith('@') or channel_identifier.startswith('-100')):
        bot.reply_to(message, "❌ Неверный формат. Используйте @username или -100...")
        return
    
    bot.reply_to(message, f"🔍 Начинаю анализ канала {channel_identifier}...")
    
    # Запускаем анализ в фоне
    def analyze_channel():
        try:
            if not channel_monitor:
                bot.send_message(message.chat.id, "❌ Монитор каналов не инициализирован. Проверьте API_ID и API_HASH.")
                return
            
            # Запускаем асинхронную задачу
            async def analyze():
                success = await channel_monitor.monitor_channel(channel_identifier)
                if success:
                    stats = await channel_monitor.get_detailed_stats(channel_identifier, days=7)
                    if stats:
                        response = format_channel_stats(stats)
                        bot.send_message(message.chat.id, response, parse_mode='Markdown')
                    else:
                        bot.send_message(message.chat.id, "✅ Канал добавлен, но статистика недоступна")
                else:
                    bot.send_message(message.chat.id, "❌ Не удалось получить данные канала. Проверьте:\n1. Бот добавлен как администратор\n2. Канал существует\n3. Права 'Изменение сообщений'")
            
            asyncio.run(analyze())
            
        except Exception as e:
            logger.error(f"Ошибка анализа канала: {e}")
            bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)}")
    
    thread = threading.Thread(target=analyze_channel, daemon=True)
    thread.start()

@bot.message_handler(commands=['channel_stats'])
def channel_stats_command(message):
    """Статистика конкретного канала"""
    user_id = message.from_user.id
    add_user(user_id, message.from_user.username, message.from_user.first_name)
    
    args = message.text.split()
    if len(args) < 2:
        # Показываем список отслеживаемых каналов
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT channel_id, channel_name, username, last_updated 
            FROM channels 
            WHERE is_active = 1 
            ORDER BY last_updated DESC 
            LIMIT 10
        ''')
        channels = cursor.fetchall()
        conn.close()
        
        if not channels:
            response = "📭 Нет отслеживаемых каналов.\nИспользуйте `/add_channel @username` чтобы добавить."
        else:
            response = "📋 **ОТСЛЕЖИВАЕМЫЕ КАНАЛЫ:**\n\n"
            for i, channel in enumerate(channels, 1):
                updated = channel['last_updated'][:16] if channel['last_updated'] else 'никогда'
                response += f"{i}. **{channel['channel_name']}**\n"
                if channel['username']:
                    response += f"   @{channel['username']}\n"
                response += f"   📅 Обновлено: {updated}\n"
                response += f"   📊 `/channel_stats {channel['channel_id']}`\n"
                response += "   ─────────────\n"
        
        bot.reply_to(message, response, parse_mode='Markdown')
        return
    
    channel_identifier = args[1].strip()
    days = 7
    if len(args) > 2:
        try:
            days = min(max(int(args[2]), 1), 30)
        except:
            pass
    
    bot.reply_to(message, f"📊 Анализирую статистику за {days} дней...")
    
    def get_stats():
        try:
            if not channel_monitor:
                bot.send_message(message.chat.id, "❌ Монитор каналов не инициализирован.")
                return
            
            async def fetch_stats():
                stats = await channel_monitor.get_detailed_stats(channel_identifier, days)
                if stats:
                    response = format_channel_stats(stats)
                    bot.send_message(message.chat.id, response, parse_mode='Markdown')
                else:
                    bot.send_message(message.chat.id, "❌ Не удалось получить статистику. Проверьте идентификатор канала.")
            
            asyncio.run(fetch_stats())
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)}")
    
    thread = threading.Thread(target=get_stats, daemon=True)
    thread.start()

def format_channel_stats(stats_data):
    """Форматирование статистики канала для отправки"""
    channel = stats_data['channel_info']
    stats = stats_data['stats']
    days = stats_data['period_days']
    
    response = f"📊 **СТАТИСТИКА КАНАЛА**\n\n"
    response += f"**{channel['title']}**\n"
    if channel.get('username'):
        response += f"@{channel['username']}\n"
    response += f"👥 Подписчиков: {channel.get('participants_count', 'N/A'):,}\n"
    response += f"📅 Период: {days} дней\n"
    response += f"📝 Сообщений: {stats['total_messages']}\n\n"
    
    response += f"👁️ **ПРОСМОТРЫ:**\n"
    response += f"• Всего: {stats['total_views']:,}\n"
    response += f"• В среднем: {stats['avg_views']:,.0f} на пост\n\n"
    
    response += f"📤 **РЕПОСТЫ:**\n"
    response += f"• Всего: {stats['total_forwards']:,}\n"
    response += f"• В среднем: {stats['avg_forwards']:,.1f} на пост\n\n"
    
    if stats['reactions_summary']:
        response += f"🔥 **РЕАКЦИИ:**\n"
        for emoji, count in list(stats['reactions_summary'].items())[:5]:
            response += f"• {emoji}: {count:,}\n"
        response += "\n"
    
    response += f"🏆 **ТОП-3 ПОСТА:**\n"
    for i, post in enumerate(stats['top_posts'][:3], 1):
        medal = ['🥇', '🥈', '🥉'][i-1] if i <= 3 else f"{i}."
        response += f"{medal} **{post['views']:,}** просмотров\n"
        response += f"   {post['text']}\n"
        response += f"   📅 {post['date'][:10] if post['date'] else 'N/A'}\n"
        response += "   ─────────────\n"
    
    # Ежедневная статистика
    if stats['daily_stats']:
        response += f"\n📈 **ДНЕВНАЯ СТАТИСТИКА:**\n"
        for day, day_stats in list(stats['daily_stats'].items())[-5:]:
            avg_views = day_stats['views'] / max(day_stats['posts'], 1)
            response += f"• {day}: {day_stats['posts']} постов, {day_stats['views']:,} просмотров (avg: {avg_views:,.0f})\n"
    
    response += f"\n🔄 *Используйте `/update_channel {channel['id']}` для обновления*"
    
    return response

@bot.message_handler(commands=['update_channel'])
def update_channel_command(message):
    """Обновление данных канала"""
    user_id = message.from_user.id
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "📝 Использование: `/update_channel @username_или_id`", parse_mode='Markdown')
        return
    
    channel_identifier = args[1].strip()
    
    bot.reply_to(message, f"🔄 Обновляю данные канала {channel_identifier}...")
    
    def update_channel():
        try:
            if not channel_monitor:
                bot.send_message(message.chat.id, "❌ Монитор каналов не инициализирован.")
                return
            
            async def update():
                success = await channel_monitor.monitor_channel(channel_identifier)
                if success:
                    bot.send_message(message.chat.id, f"✅ Данные канала {channel_identifier} обновлены!")
                else:
                    bot.send_message(message.chat.id, f"❌ Не удалось обновить канал {channel_identifier}")
            
            asyncio.run(update())
            
        except Exception as e:
            logger.error(f"Ошибка обновления канала: {e}")
            bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)}")
    
    thread = threading.Thread(target=update_channel, daemon=True)
    thread.start()

@bot.message_handler(commands=['compare'])
def compare_channels_command(message):
    """Сравнение нескольких каналов"""
    user_id = message.from_user.id
    add_user(user_id, message.from_user.username, message.from_user.first_name)
    
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "📝 Использование: `/compare @канал1 @канал2 [дней=7]`", parse_mode='Markdown')
        return
    
    channels = args[1:3]
    days = 7
    if len(args) > 3:
        try:
            days = min(max(int(args[3]), 1), 30)
        except:
            pass
    
    bot.reply_to(message, f"📊 Сравниваю каналы за {days} дней...")
    
    def compare():
        try:
            if not channel_monitor:
                bot.send_message(message.chat.id, "❌ Монитор каналов не инициализирован.")
                return
            
            async def fetch_comparison():
                results = []
                for channel in channels:
                    stats = await channel_monitor.get_detailed_stats(channel, days)
                    if stats:
                        results.append({
                            'channel': stats['channel_info']['title'],
                            'stats': stats['stats']
                        })
                
                if len(results) == 2:
                    response = format_comparison(results, days)
                    bot.send_message(message.chat.id, response, parse_mode='Markdown')
                else:
                    bot.send_message(message.chat.id, "❌ Не удалось сравнить каналы. Проверьте идентификаторы.")
            
            asyncio.run(fetch_comparison())
            
        except Exception as e:
            logger.error(f"Ошибка сравнения каналов: {e}")
            bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)}")
    
    thread = threading.Thread(target=compare, daemon=True)
    thread.start()

def format_comparison(results, days):
    """Форматирование сравнения каналов"""
    chan1, chan2 = results[0], results[1]
    
    response = f"⚖️ **СРАВНЕНИЕ КАНАЛОВ**\n\n"
    response += f"📅 Период: {days} дней\n\n"
    
    # Таблица сравнения
    response += "| Метрика | **{0}** | **{1}** |\n".format(
        chan1['channel'][:15], 
        chan2['channel'][:15]
    )
    response += "|---------|---------|---------|\n"
    
    metrics = [
        ("📝 Посты", chan1['stats']['total_messages'], chan2['stats']['total_messages']),
        ("👁️ Просмотры", chan1['stats']['total_views'], chan2['stats']['total_views']),
        ("📤 Репосты", chan1['stats']['total_forwards'], chan2['stats']['total_forwards']),
        ("📊 Средние просмотры", int(chan1['stats']['avg_views']), int(chan2['stats']['avg_views'])),
        ("🚀 Эффективность", 
         f"{chan1['stats']['avg_views']/max(chan1['stats']['avg_forwards'], 1):.1f}x", 
         f"{chan2['stats']['avg_views']/max(chan2['stats']['avg_forwards'], 1):.1f}x")
    ]
    
    for name, val1, val2 in metrics:
        winner = "🏆" if val1 > val2 else ("🤝" if val1 == val2 else "")
        response += f"| {name} | {val1:,} {winner} | {val2:,} |\n"
    
    # Анализ
    response += f"\n📈 **АНАЛИЗ:**\n"
    
    if chan1['stats']['avg_views'] > chan2['stats']['avg_views']:
        response += f"• **{chan1['channel']}** имеет более высокий средний охват\n"
    else:
        response += f"• **{chan2['channel']}** имеет более высокий средний охват\n"
    
    engagement1 = chan1['stats']['avg_views'] / max(chan1['stats']['avg_forwards'], 1)
    engagement2 = chan2['stats']['avg_views'] / max(chan2['stats']['avg_forwards'], 1)
    
    if engagement1 > engagement2:
        response += f"• **{chan1['channel']}** имеет лучшее соотношение просмотров/репостов\n"
    else:
        response += f"• **{chan2['channel']}** имеет лучшее соотношение просмотров/репостов\n"
    
    return response

# ========== ФОНОВЫЕ ЗАДАЧИ ==========
def background_monitoring():
    """Фоновый мониторинг каналов"""
    while True:
        try:
            if channel_monitor:
                # Получаем список активных каналов
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT channel_id, username 
                    FROM channels 
                    WHERE is_active = 1 
                    ORDER BY last_updated ASC 
                    LIMIT 5
                ''')
                channels = cursor.fetchall()
                conn.close()
                
                # Обновляем каждый канал
                for channel in channels:
                    try:
                        identifier = f"@{channel['username']}" if channel['username'] else str(channel['channel_id'])
                        
                        async def update():
                            await channel_monitor.monitor_channel(identifier)
                        
                        asyncio.run(update())
                        logger.info(f"✅ Фоновое обновление канала {identifier}")
                        time.sleep(10)  # Пауза между каналами
                        
                    except Exception as e:
                        logger.error(f"❌ Ошибка фонового обновления канала {channel['channel_id']}: {e}")
            
            # Ж
