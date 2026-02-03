import re

def fix_bot_links():
    """Автоматическое исправление ссылок на бота в app.py"""
    
    # Введите username вашего бота (без @)
    bot_username = input("Введите username вашего бота (без @): ").strip()
    if not bot_username:
        bot_username = "goonlord_analytics_bot"  # замените на ваш
    
    # Читаем файл
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Заменяем все вхождения
    old_link = 'https://t.me/YOUR_BOT_USERNAME'
    new_link = f'https://t.me/{bot_username}'
    
    content_fixed = content.replace(old_link, new_link)
    
    # Также заменяем другие возможные варианты
    content_fixed = content_fixed.replace('YOUR_BOT_USERNAME', bot_username)
    
    # Сохраняем
    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(content_fixed)
    
    print(f"✅ Ссылки заменены на: https://t.me/{bot_username}")
    print("Файл app.py обновлен!")

if __name__ == '__main__':
    fix_bot_links()
