# Тайный гость — Telegram бот

Бот регистрирует гостей в Planfix c использованием шаблона контакта `413` и дружелюбного диалога.

## Быстрый старт

### Автоматическая настройка (рекомендуется)

#### Windows (PowerShell)
```powershell
# Настройка окружения (создание venv, установка зависимостей, создание .env)
.\setup.ps1

# Редактирование .env файла (заполните все переменные окружения)
notepad .env

# Запуск бота
.\run.ps1

# Запуск тестов
.\test.ps1
```

#### Linux/macOS (Bash)
```bash
# Настройка окружения (создание venv, установка зависимостей, создание .env)
chmod +x setup.sh run.sh test.sh
./setup.sh

# Редактирование .env файла (заполните все переменные окружения)
nano .env  # или используйте ваш любимый редактор

# Запуск бота
./run.sh

# Запуск тестов
./test.sh
```

### Ручная настройка

1. Склонируйте репозиторий и перейдите в директорию проекта.

2. Скопируйте `env.example` в `.env` и заполните значения:

   ```bash
   # Windows
   copy env.example .env
   
   # Linux/macOS
   cp env.example .env
   ```

   | Переменная            | Описание                                                       |
   |-----------------------|----------------------------------------------------------------|
   | `BOT_TOKEN`           | Токен Telegram-бота.                                           |
   | `PLANFIX_BASE_URL`    | Базовый URL Planfix REST (`https://conquest.planfix.ru/rest/`). |
   | `PLANFIX_TOKEN`       | Сервисный токен Planfix (пример: `95f77097e87d10272ad5dc904c6bc95e`). |
   | `ADMIN_NAME`          | Ник администратора в Telegram (например, `@YP6AH`).           |
   | `ADMIN_CHAT_ID`       | ID чата/пользователя для уведомлений (опционально).           |
   | `PLANFIX_TEMPLATE_ID` | ID шаблона контакта (по умолчанию `413`).                     |

3. Создайте виртуальное окружение и установите зависимости:

   ```bash
   # Windows
   python -m venv .venv
   .venv\Scripts\activate
   
   # Linux/macOS
   python3 -m venv .venv
   source .venv/bin/activate
   
   # Установка зависимостей (для обеих платформ)
   pip install -r requirements.txt
   ```

4. Запустите бота:

   ```bash
   python -m bot.main
   ```

## Docker

```bash
docker build -t planfix-guest-bot .
docker run --env-file .env planfix-guest-bot
```

Или используйте Compose:

```bash
docker-compose up --build
```

## Тестирование

### Быстрый запуск тестов

```bash
# Windows (PowerShell)
.\test.ps1

# Linux/macOS (Bash)
./test.sh
```

### Ручной запуск тестов

```bash
# Активация виртуального окружения
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/macOS

# Запуск всех тестов
pytest

# Запуск с подробным выводом
pytest -v

# Запуск конкретного тестового файла
pytest tests/test_validators.py
pytest tests/test_planfix_client.py

# Запуск с покрытием кода (если установлен pytest-cov)
pytest --cov=bot --cov-report=html
```

### Структура тестов

- `tests/test_validators.py` — тесты для валидации пользовательского ввода
- `tests/test_planfix_client.py` — тесты для клиента Planfix API

Все тесты используют `respx` для мокирования HTTP запросов к Planfix API.

## Архитектура

- `bot/main.py` — точка входа, настройка aiogram и Planfix клиента.
- `bot/config.py` — загрузка переменных окружения через Pydantic.
- `bot/handlers/registration.py` — шаги диалога, валидация, подтверждение и отправка данных.
- `bot/services/planfix.py` — httpx-клиент с retry и логированием.
- `bot/services/validators.py` — общие проверки данных.
- `bot/schemas.py` — структуры данных и маппинг в формат Planfix.
- `tests/` — юнит-тесты для валидации и Planfix клиента (через `respx`).

## Примеры запросов к Planfix

```bash
curl -X GET "https://conquest.planfix.ru/rest/contact/templates" \
  -H "Authorization: Bearer $PLANFIX_TOKEN"

curl -X POST "https://conquest.planfix.ru/rest/contact/list" \
  -H "Authorization: Bearer $PLANFIX_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "offset": 0,
        "pageSize": 100,
        "fields": "id,name,midname,lastname,phones",
        "filters": [
          {"type": 4003, "operator": "equal", "value": "+79260000000"}
        ]
      }'

curl -X POST "https://conquest.planfix.ru/rest/contact/" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $PLANFIX_TOKEN" \
  -d '{
        "templateId": 413,
        "lastName": "Иванов",
        "firstName": "Иван",
        "phone": "+79260000000",
        "birthday": "1985-01-01",
        "customFields": {"1": "Москва"}
      }'
```

## Планируемые права доступа

Используйте токен с разрешениями: `comment_add`, `comment_delete`, `comment_readonly`, `comment_update`, `contact_add`, `contact_readonly`, `contact_update`, `custom_field_add`, `custom_field_set_add`, `datatag_add`, `datatag_delete`, `datatag_readonly`, `datatag_update`, `directory_add`, `directory_delete`, `directory_readonly`, `directory_update`, `file_add`, `file_delete`, `file_readonly`, `object_readonly`, `process_readonly`, `project_add`, `project_readonly`, `project_update`, `report_readonly`, `task_add`, `task_readonly`, `task_update`, `user_add`, `user_readonly`, `user_update`.

## Локальная разработка

### Структура проекта

```
mgreg-bot/
├── bot/                    # Основной код бота
│   ├── handlers/          # Обработчики сообщений
│   ├── services/          # Бизнес-логика и интеграции
│   ├── main.py            # Точка входа
│   └── ...
├── tests/                  # Тесты
├── .env                    # Переменные окружения (не в git)
├── env.example            # Шаблон переменных окружения
├── requirements.txt       # Зависимости Python
├── pytest.ini            # Конфигурация pytest
├── setup.ps1 / setup.sh  # Скрипты автоматической настройки
├── run.ps1 / run.sh      # Скрипты запуска бота
└── test.ps1 / test.sh    # Скрипты запуска тестов
```

### Полезные команды

```bash
# Проверка кода (если используется линтер)
flake8 bot tests

# Проверка типов (если используется mypy)
mypy bot

# Форматирование кода (если используется black)
black bot tests
```

### Отладка

Для отладки бота локально:

1. Убедитесь, что `.env` файл содержит корректные токены
2. Проверьте логи в консоли (структурированный JSON формат)
3. Используйте тестовый режим Planfix API (если доступен)
4. Для тестирования handlers можно использовать `python -m pytest` с мокированием

## Полезные заметки

- Шаблон контакта (`templateId`) переопределяется через переменную окружения `PLANFIX_TEMPLATE_ID`.
- Токены и PII не логируются; логируются статусы запросов и ID контактов.
- При дублирующемся телефоне бот предложит обновить данные существующего контакта.
- При успешной регистрации бот уведомляет администратора (если указан `ADMIN_CHAT_ID`).
- Все скрипты автоматически активируют виртуальное окружение и проверяют зависимости.

