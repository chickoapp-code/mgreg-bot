# PowerShell скрипт для запуска бота
Write-Host "=== Запуск Telegram бота ===" -ForegroundColor Green

# Проверка виртуального окружения
if (-not (Test-Path ".venv")) {
    Write-Host "Ошибка: Виртуальное окружение не найдено." -ForegroundColor Red
    Write-Host "Запустите сначала: .\setup.ps1" -ForegroundColor Yellow
    exit 1
}

# Проверка .env файла
if (-not (Test-Path ".env")) {
    Write-Host "Ошибка: .env файл не найден." -ForegroundColor Red
    Write-Host "Скопируйте env.example в .env и заполните значения." -ForegroundColor Yellow
    exit 1
}

# Активация виртуального окружения
Write-Host "Активация виртуального окружения..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

# Проверка зависимостей
Write-Host "Проверка зависимостей..." -ForegroundColor Yellow
$installed = pip list | Select-String "aiogram"
if (-not $installed) {
    Write-Host "Установка зависимостей..." -ForegroundColor Yellow
    pip install -r requirements.txt
}

# Запуск бота
Write-Host "`nЗапуск бота..." -ForegroundColor Green
Write-Host "Для остановки нажмите Ctrl+C" -ForegroundColor Yellow
Write-Host ""
python -m bot.main

