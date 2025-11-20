# Тайный гость — Telegram бот

Бот регистрирует гостей в Planfix c использованием шаблона контакта `413` и дружелюбного диалога.

## Быстрый старт

1. Склонируйте репозиторий и перейдите в директорию проекта.
2. Скопируйте `env.example` в `.env` и заполните значения:

   ```bash
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

3. Установите зависимости:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   source .venv/bin/activate  # Linux/macOS
   pip install -r requirements.txt
   ```

   > Вместо `pip` можете использовать `poetry install` — все зависимости указаны в `requirements.txt`.

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

## Тесты

```bash
pytest
```

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

## Полезные заметки

- Шаблон контакта (`templateId`) переопределяется через переменную окружения `PLANFIX_TEMPLATE_ID`.
- Токены и PII не логируются; логируются статусы запросов и ID контактов.
- При дублирующемся телефоне бот предложит обновить данные существующего контакта.
- При успешной регистрации бот уведомляет администратора (если указан `ADMIN_CHAT_ID`).

