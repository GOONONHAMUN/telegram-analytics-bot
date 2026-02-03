#!/bin/bash
# Установка зависимостей для Render

echo "🚀 Установка зависимостей..."

# Устанавливаем зависимости с pre-built wheels
pip install --upgrade pip
pip install wheel

# Основные зависимости
pip install Flask==2.3.3
pip install pyTelegramBotAPI==4.30.0

# Пытаемся установить telethon с pre-built wheel
pip install --no-cache-dir --only-binary :all: telethon==1.34.0 || \
pip install telethon==1.34.0 --no-deps || \
echo "⚠️ Telethon не установлен, используем демо-режим"

echo "✅ Зависимости установлены"
