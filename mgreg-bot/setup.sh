#!/bin/bash
# Bash скрипт для настройки локального окружения (Linux/macOS)

echo "=== Настройка локального окружения для бота ==="

# Проверка Python
echo ""
echo "Проверка Python..."
if ! command -v python3 &> /dev/null; then
    echo "Ошибка: Python 3 не найден. Установите Python 3.12 или выше."
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo "Найден: $PYTHON_VERSION"

# Создание виртуального окружения
echo ""
echo "Создание виртуального окружения..."
if [ -d ".venv" ]; then
    echo "Виртуальное окружение уже существует."
else
    python3 -m venv .venv
    echo "Виртуальное окружение создано."
fi

# Активация виртуального окружения
echo ""
echo "Активация виртуального окружения..."
source .venv/bin/activate

# Обновление pip
echo ""
echo "Обновление pip..."
python -m pip install --upgrade pip

# Установка зависимостей
echo ""
echo "Установка зависимостей..."
pip install -r requirements.txt

# Создание .env файла если его нет
echo ""
echo "Проверка .env файла..."
if [ ! -f ".env" ]; then
    if [ -f "env.example" ]; then
        cp env.example .env
        echo ".env файл создан из env.example. Не забудьте заполнить значения!"
    else
        echo "Предупреждение: env.example не найден."
    fi
else
    echo ".env файл уже существует."
fi

echo ""
echo "=== Настройка завершена! ==="
echo ""
echo "Следующие шаги:"
echo "1. Отредактируйте файл .env и заполните все переменные окружения"
echo "2. Активируйте виртуальное окружение: source .venv/bin/activate"
echo "3. Запустите бота: python -m bot.main"
echo "   или используйте скрипт: ./run.sh"
echo "4. Запустите тесты: pytest"
echo "   или используйте скрипт: ./test.sh"

