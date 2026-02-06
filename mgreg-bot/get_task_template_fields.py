#!/usr/bin/env python3
"""Скрипт для получения ID кастомных полей шаблона задачи в Planfix.

Использование:
    python get_task_template_fields.py

Требуется в .env файле:
    PLANFIX_BASE_URL=https://your-account.planfix.ru/rest/
    PLANFIX_TOKEN=your_service_token_here
    PLANFIX_TASK_TEMPLATE_IDS=123,456  # ID шаблонов задач через запятую (опционально)
    PLANFIX_TASK_NUMBER=86190  # Номер задачи для /customfield/task/{id} (опционально)
"""

import asyncio
import json
import os
from dotenv import load_dotenv
import httpx

load_dotenv()

PLANFIX_BASE_URL = os.getenv("PLANFIX_BASE_URL", "https://conquest.planfix.ru/rest/")
PLANFIX_TOKEN = os.getenv("PLANFIX_TOKEN")
PLANFIX_TASK_TEMPLATE_IDS = os.getenv("PLANFIX_TASK_TEMPLATE_IDS", "")
PLANFIX_TASK_NUMBER = os.getenv("PLANFIX_TASK_NUMBER", "")  # Номер задачи для /customfield/task/{id}


async def get_task_templates():
    """Получить список шаблонов задач."""
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {PLANFIX_TOKEN}"}
        response = await client.get(
            f"{PLANFIX_BASE_URL.rstrip('/')}/task/templates",
            headers=headers,
            params={"fields": "id,name,customFields"},
        )
        if response.status_code >= 400:
            print(f"❌ Ошибка получения шаблонов: {response.status_code}")
            print(response.text)
            return []
        data = response.json()
        return data.get("templates", [])


def _get_custom_fields_list(data: dict) -> list:
    """Planfix API возвращает customfields (lowercase), не customFields."""
    return data.get("customfields") or data.get("customFields") or []


async def get_all_task_custom_fields():
    """Получить список всех кастомных полей задач (GET /customfield/task)."""
    url = f"{PLANFIX_BASE_URL.rstrip('/')}/customfield/task"
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {PLANFIX_TOKEN}"}
        response = await client.get(
            url,
            headers=headers,
            params={"fields": "id,name,names,type"},
        )
        if response.status_code >= 400:
            print(f"❌ Ошибка GET {url}: {response.status_code}")
            print(response.text[:500])
            return []
        data = response.json()
        fields = _get_custom_fields_list(data)
        if not fields:
            keys = list(data.keys()) if isinstance(data, dict) else "не dict"
            print(f"⚠️  В ответе нет customfields. Ключи: {keys}")
            if isinstance(data, dict) and "error" in data:
                print(f"   Ошибка API: {data.get('error', data)}")
        return fields


async def get_custom_fields_for_task(task_number: str | int) -> list:
    """Получить кастомные поля для конкретной задачи (GET /customfield/task/{id})."""
    url = f"{PLANFIX_BASE_URL.rstrip('/')}/customfield/task/{task_number}"
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {PLANFIX_TOKEN}"}
        response = await client.get(
            url,
            headers=headers,
            params={"fields": "id,name,names,type"},
        )
        if response.status_code >= 400:
            print(f"❌ Ошибка GET {url}: {response.status_code}")
            print(response.text[:500])
            return []
        data = response.json()
        return _get_custom_fields_list(data)


async def get_task_template_by_id(template_id: int):
    """Получить конкретный шаблон задачи по ID."""
    templates = await get_task_templates()
    for template in templates:
        if int(template.get("id", 0)) == int(template_id):
            return template
    return None


async def main():
    """Основная функция."""
    if not PLANFIX_TOKEN:
        print("❌ Ошибка: PLANFIX_TOKEN не указан в .env файле")
        return

    print("=" * 80)
    print("📋 Получение кастомных полей шаблонов задач Planfix")
    print("=" * 80)
    print()

    # Получить все кастомные поля задач
    print("🔍 Получение списка всех кастомных полей задач (GET /customfield/task)...")
    all_fields = await get_all_task_custom_fields()

    # Альтернатива: поля для конкретной задачи (если указан PLANFIX_TASK_NUMBER)
    if not all_fields and PLANFIX_TASK_NUMBER:
        print(f"🔍 Альтернатива: поля для задачи №{PLANFIX_TASK_NUMBER} (GET /customfield/task/{{id}})...")
        all_fields = await get_custom_fields_for_task(PLANFIX_TASK_NUMBER)
    
    if all_fields:
        print(f"✅ Найдено {len(all_fields)} кастомных полей:\n")
        print("-" * 80)
        print(f"{'ID':<10} {'Название (RU)':<40} {'Тип':<20}")
        print("-" * 80)
        for field in sorted(all_fields, key=lambda x: int(x.get("id", 0))):
            field_id = field.get("id")
            names = field.get("names", {})
            name_ru = names.get("ru") or names.get("name") or field.get("name", "N/A")
            field_type = field.get("type", "N/A")
            print(f"{field_id:<10} {name_ru:<40} {field_type:<20}")
        print("-" * 80)
        print()
    else:
        print("⚠️  Кастомные поля не найдены или ошибка получения")
        print()

    # Получить шаблоны задач
    print("🔍 Получение шаблонов задач...")
    templates = await get_task_templates()
    
    if not templates:
        print("⚠️  Шаблоны задач не найдены или ошибка получения")
        return

    print(f"✅ Найдено {len(templates)} шаблонов задач\n")

    # Если указаны конкретные ID шаблонов
    template_ids_to_show = []
    if PLANFIX_TASK_TEMPLATE_IDS:
        template_ids_to_show = [int(x.strip()) for x in PLANFIX_TASK_TEMPLATE_IDS.split(",") if x.strip()]
        print(f"📌 Показаны только шаблоны с ID: {', '.join(map(str, template_ids_to_show))}\n")

    # Показать информацию о шаблонах
    for template in templates:
        template_id = template.get("id")
        template_name = template.get("name", "N/A")
        custom_fields = _get_custom_fields_list(template)

        # Показать только нужные шаблоны (сравниваем по int)
        if template_ids_to_show and int(template_id or 0) not in template_ids_to_show:
            continue

        print("=" * 80)
        print(f"📝 Шаблон: {template_name} (ID: {template_id})")
        print("=" * 80)

        if custom_fields:
            print(f"✅ Найдено {len(custom_fields)} кастомных полей в шаблоне:\n")
            print("-" * 80)
            print(f"{'ID':<10} {'Название':<50} {'Тип':<20}")
            print("-" * 80)
            for field in sorted(custom_fields, key=lambda x: int(x.get("id", 0))):
                field_id = field.get("id")
                field_name = field.get("name") or field.get("label", "N/A")
                field_type = field.get("type", "N/A")
                print(f"{field_id:<10} {field_name:<50} {field_type:<20}")
            print("-" * 80)
        else:
            print("⚠️  Кастомные поля не найдены в этом шаблоне")
        print()

    # Рекомендации по настройке
    print("=" * 80)
    print("📝 Рекомендации для .env файла:")
    print("=" * 80)
    print()
    print("Найдите нужные поля выше и добавьте их ID в .env файл:")
    print()
    print("# Custom fields for guest assignment")
    print("GUEST_FIELD_ID=XXX  # ID поля 'Выбранный тайный гость'")
    print("ASSIGNMENT_SOURCE_FIELD_ID=XXX  # ID поля 'Источник назначения'")
    print()
    print("# Custom fields for form results")
    print("SCORE_FIELD_ID=XXX  # ID поля 'Итоговый балл'")
    print("RESULT_STATUS_FIELD_ID=XXX  # ID поля 'Статус результата'")
    print("SESSION_ID_FIELD_ID=XXX  # ID поля 'ID сессии анкеты'")
    print()
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())




