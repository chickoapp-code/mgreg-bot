#!/usr/bin/env python
"""Скрипт для установки зависимостей и запуска бота."""
import subprocess
import sys
import os
from pathlib import Path

def main():
    # Получаем директорию проекта
    project_dir = Path(__file__).parent
    os.chdir(project_dir)
    
    venv_python = project_dir / ".venv" / "Scripts" / "python.exe"
    
    if not venv_python.exists():
        print("Виртуальное окружение не найдено. Создаю...")
        subprocess.run([sys.executable, "-m", "venv", ".venv"], check=True)
        venv_python = project_dir / ".venv" / "Scripts" / "python.exe"
    
    print("Проверка зависимостей...")
    # Проверяем установлен ли aiogram
    result = subprocess.run(
        [str(venv_python), "-m", "pip", "list"],
        capture_output=True,
        text=True
    )
    
    if "aiogram" not in result.stdout:
        print("Установка зависимостей...")
        requirements_file = project_dir / "requirements.txt"
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-r", str(requirements_file)],
            check=True
        )
    
    # Проверка .env файла
    env_file = project_dir / ".env"
    if not env_file.exists():
        env_example = project_dir / "env.example"
        if env_example.exists():
            print("Создание .env файла из env.example...")
            import shutil
            shutil.copy(env_example, env_file)
            print("ВАЖНО: Отредактируйте файл .env и заполните все переменные окружения перед запуском!")
            print(f"Файл находится здесь: {env_file}")
            return
        else:
            print("ОШИБКА: Файл env.example не найден!")
            return
    
    # Проверка заполненности .env
    with open(env_file, 'r', encoding='utf-8') as f:
        env_content = f.read()
        if 'your_telegram_bot_token_here' in env_content or 'your_planfix_service_token_here' in env_content:
            print("ВНИМАНИЕ: Файл .env содержит значения по умолчанию!")
            print("Отредактируйте файл .env и заполните реальные токены перед запуском.")
            print(f"Файл находится здесь: {env_file}")
            return
    
    print("\nЗапуск бота...")
    print("Для остановки нажмите Ctrl+C\n")
    
    # Запуск бота
    subprocess.run([str(venv_python), "-m", "bot.main"], cwd=project_dir)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nБот остановлен пользователем.")
    except Exception as e:
        print(f"\nОшибка: {e}")
        sys.exit(1)

