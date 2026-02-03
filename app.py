import os
from flask import Flask, request, jsonify
import telebot

# Создаем Flask приложение
app = Flask(__name__)

# Получаем токен из переменных окружения
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    print("⚠️ ВНИМАНИЕ: BOT_TOKEN не установлен!")
    print("Добавьте BOT_TOKEN в Environment Variables на Render")
    # Для теста можно временно указать здесь
    # BOT_TOKEN = "ваш_токен"

# Создаем бота
bot = telebot.TeleBot(BOT_TOKEN) if BOT_TOKEN else None

# Простейшая команда бота
@bot.message_handler(commands=['start'])
def start(message):
    if bot:
        bot.reply_to(message, "✅ Бот работает на Render!")

# Маршруты Flask
@app.route('/')
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Telegram Bot</title>
        <meta charset="utf-8">
    </head>
    <body>
        <h1>🤖 Telegram Bot работает!</h1>
        <p>Статус: ✅ Активен</p>
        <p>Если бот не отвечает, проверьте BOT_TOKEN</p>
    </body>
    </html>
    """

@app.route('/health')
def health_check():
    """Проверка здоровья для Render"""
    return jsonify({
        "status": "healthy",
        "service": "telegram-bot",
        "bot_configured": bool(BOT_TOKEN)
    }), 200

@app.route('/webhook', methods=['POST'])
def webhook():
    """Вебхук для Telegram"""
    if not bot:
        return 'Bot not configured', 500
        
    if request.headers.get('content-type') == 'application/json':
        try:
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            return ''
        except Exception as e:
            print(f"Ошибка вебхука: {e}")
            return 'Error', 500
    return 'Bad request', 400

# ЗАПУСК ПРИЛОЖЕНИЯ
if __name__ == '__main__':
    print("🚀 Запуск приложения...")
    print(f"BOT_TOKEN установлен: {'✅ Да' if BOT_TOKEN else '❌ Нет'}")
    
    # Получаем порт от Render
    port = int(os.environ.get('PORT', 10000))
    print(f"🌐 Запускаюсь на порту: {port}")
    
    # Запускаем Flask
    app.run(host='0.0.0.0', port=port, debug=False)



