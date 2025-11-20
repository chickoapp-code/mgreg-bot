@echo off
chcp 65001 >nul
echo === Запуск Telegram бота ===
echo.

cd /d "%~dp0"

if not exist ".venv" (
    echo Виртуальное окружение не найдено. Создаю...
    python -m venv .venv
    if errorlevel 1 (
        echo Ошибка при создании виртуального окружения!
        pause
        exit /b 1
    )
)

if not exist ".env" (
    echo Создание .env файла из env.example...
    if exist "env.example" (
        copy /Y env.example .env >nul
        echo .env файл создан. Не забудьте заполнить значения!
        echo.
        notepad .env
        echo.
        echo Нажмите любую клавишу после редактирования .env файла...
        pause >nul
    ) else (
        echo ОШИБКА: Файл env.example не найден!
        pause
        exit /b 1
    )
)

echo Активация виртуального окружения...
call .venv\Scripts\activate.bat

echo Проверка зависимостей...
pip list | findstr /i "aiogram" >nul
if errorlevel 1 (
    echo Установка зависимостей...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo Ошибка при установке зависимостей!
        pause
        exit /b 1
    )
)

echo.
echo Запуск бота...
echo Для остановки нажмите Ctrl+C
echo.

python -m bot.main

pause

