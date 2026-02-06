# Как получить ID кастомных полей шаблона задачи в Planfix

Есть несколько способов получить ID кастомных полей шаблона задачи в Planfix:

## Способ 1: Использование скрипта (рекомендуется)

Запустите скрипт, который автоматически получит все кастомные поля:

```bash
python get_task_template_fields.py
```

Скрипт покажет:
- Все кастомные поля задач в вашем аккаунте Planfix
- Кастомные поля для каждого шаблона задачи (если указан `PLANFIX_TASK_TEMPLATE_IDS` в `.env`)
- Рекомендации по настройке `.env` файла

**Требования:**
- Должен быть настроен `.env` файл с `PLANFIX_TOKEN` и `PLANFIX_BASE_URL`
- Опционально: укажите `PLANFIX_TASK_TEMPLATE_IDS` для фильтрации шаблонов

## Способ 2: Через Planfix API напрямую

### Вариант A: Получить все кастомные поля задач

```bash
curl -X GET "https://your-account.planfix.ru/rest/customfield/task?fields=id,name,names,type" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Вариант B: Получить шаблоны задач с их полями

```bash
curl -X GET "https://your-account.planfix.ru/rest/task/templates?fields=id,name,customFields" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Вариант C: Использовать Python с httpx

```python
import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

async def get_fields():
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {os.getenv('PLANFIX_TOKEN')}"}
        response = await client.get(
            f"{os.getenv('PLANFIX_BASE_URL')}/customfield/task",
            headers=headers,
            params={"fields": "id,name,names,type"}
        )
        data = response.json()
        for field in data.get("customFields", []):
            print(f"ID: {field['id']}, Название: {field.get('names', {}).get('ru', field.get('name'))}")

asyncio.run(get_fields())
```

## Способ 3: Через веб-интерфейс Planfix

1. Откройте Planfix в браузере
2. Перейдите в **Настройки** → **Задачи** → **Шаблоны задач**
3. Выберите нужный шаблон
4. В разделе **Кастомные поля** вы увидите все поля с их ID
5. Или перейдите в **Настройки** → **Задачи** → **Кастомные поля** для просмотра всех полей

**Примечание:** ID кастомного поля можно увидеть в URL при редактировании поля или в настройках шаблона.

## Способ 4: Из существующей задачи

Если у вас уже есть задача, созданная из нужного шаблона:

1. Откройте задачу в Planfix
2. Перейдите в раздел с кастомными полями
3. Используйте инструменты разработчика браузера (F12) для просмотра сетевых запросов
4. При редактировании поля в ответе API будет указан ID поля

Или используйте API для получения задачи с полями:

```bash
curl -X GET "https://your-account.planfix.ru/rest/task/TASK_NUMBER?fields=customFieldData" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## После получения ID полей

Добавьте полученные ID в ваш `.env` файл:

```env
# Custom fields for guest assignment
GUEST_FIELD_ID=102  # ID поля "Выбранный тайный гость"
ASSIGNMENT_SOURCE_FIELD_ID=103  # ID поля "Источник назначения"

# Custom fields for form results
SCORE_FIELD_ID=104  # ID поля "Итоговый балл"
RESULT_STATUS_FIELD_ID=105  # ID поля "Статус результата"
SESSION_ID_FIELD_ID=106  # ID поля "ID сессии анкеты"
```

## Полезные ссылки

- [Planfix REST API документация](https://planfix.ru/docs/)
- [Swagger документация для вашего аккаунта](https://your-account.planfix.ru/rest/swagger.json)




