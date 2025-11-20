# PowerShell скрипт для настройки локального окружения
Write-Host "=== Настройка локального окружения для бота ===" -ForegroundColor Green

# Проверка Python
Write-Host "`nПроверка Python..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Ошибка: Python не найден. Установите Python 3.12 или выше." -ForegroundColor Red
    exit 1
}
Write-Host "Найден: $pythonVersion" -ForegroundColor Green

# Создание виртуального окружения
Write-Host "`nСоздание виртуального окружения..." -ForegroundColor Yellow
if (Test-Path ".venv") {
    Write-Host "Виртуальное окружение уже существует." -ForegroundColor Yellow
} else {
    python -m venv .venv
    Write-Host "Виртуальное окружение создано." -ForegroundColor Green
}

# Активация виртуального окружения
Write-Host "`nАктивация виртуального окружения..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

# Обновление pip
Write-Host "`nОбновление pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip

# Установка зависимостей
Write-Host "`nУстановка зависимостей..." -ForegroundColor Yellow
pip install -r requirements.txt

# Создание .env файла если его нет
Write-Host "`nПроверка .env файла..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    if (Test-Path "env.example") {
        Copy-Item "env.example" ".env"
        Write-Host ".env файл создан из env.example. Не забудьте заполнить значения!" -ForegroundColor Yellow
    } else {
        Write-Host "Предупреждение: env.example не найден." -ForegroundColor Yellow
    }
} else {
    Write-Host ".env файл уже существует." -ForegroundColor Green
}

Write-Host "`n=== Настройка завершена! ===" -ForegroundColor Green
Write-Host "`nСледующие шаги:" -ForegroundColor Cyan
Write-Host "1. Отредактируйте файл .env и заполните все переменные окружения" -ForegroundColor White
Write-Host "2. Активируйте виртуальное окружение: .\.venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "3. Запустите бота: python -m bot.main" -ForegroundColor White
Write-Host "   или используйте скрипт: .\run.ps1" -ForegroundColor White
Write-Host "4. Запустите тесты: pytest" -ForegroundColor White
Write-Host "   или используйте скрипт: .\test.ps1" -ForegroundColor White

