# PowerShell скрипт для запуска тестов
Write-Host "=== Запуск тестов ===" -ForegroundColor Green

# Проверка виртуального окружения
if (-not (Test-Path ".venv")) {
    Write-Host "Ошибка: Виртуальное окружение не найдено." -ForegroundColor Red
    Write-Host "Запустите сначала: .\setup.ps1" -ForegroundColor Yellow
    exit 1
}

# Активация виртуального окружения
Write-Host "Активация виртуального окружения..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

# Проверка зависимостей для тестирования
Write-Host "Проверка зависимостей для тестирования..." -ForegroundColor Yellow
$installed = pip list | Select-String "pytest"
if (-not $installed) {
    Write-Host "Установка зависимостей..." -ForegroundColor Yellow
    pip install -r requirements.txt
}

# Запуск тестов
Write-Host "`nЗапуск тестов..." -ForegroundColor Green
Write-Host ""

# Запуск pytest с подробным выводом
pytest -v --tb=short

# Проверка результата
if ($LASTEXITCODE -eq 0) {
    Write-Host "`n=== Все тесты прошли успешно! ===" -ForegroundColor Green
} else {
    Write-Host "`n=== Некоторые тесты провалились ===" -ForegroundColor Red
    exit $LASTEXITCODE
}

