#!/bin/bash
# Bash скрипт для запуска бота (Linux/macOS)

echo "=== Запуск Telegram бота ==="

# Проверка виртуального окружения
if [ ! -d ".venv" ]; then
    echo "Ошибка: Виртуальное окружение не найдено."
    echo "Запустите сначала: ./setup.sh"
    exit 1
fi

# Проверка .env файла
if [ ! -f ".env" ]; then
    echo "Ошибка: .env файл не найден."
    echo "Скопируйте env.example в .env и заполните значения."
    exit 1
fi

# Активация виртуального окружения
echo "Активация виртуального окружения..."
source .venv/bin/activate

# Проверка зависимостей
echo "Проверка зависимостей..."
if ! pip list | grep -q "aiogram"; then
    echo "Установка зависимостей..."
    pip install -r requirements.txt
fi

# Запуск бота
echo ""
echo "Запуск бота..."
echo "Для остановки нажмите Ctrl+C"
echo ""
python -m bot.main

