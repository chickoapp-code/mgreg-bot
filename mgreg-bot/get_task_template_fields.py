#!/usr/bin/env python3
"""Скрипт для получения ID кастомных полей шаблона задачи в Planfix.

Использование:
    python get_task_template_fields.py

Требуется в .env файле:
    PLANFIX_BASE_URL=https://your-account.planfix.ru/rest/
    PLANFIX_TOKEN=your_service_token_here
    PLANFIX_TASK_TEMPLATE_IDS=123,456  # ID шаблонов задач через запятую
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


async def get_all_task_custom_fields():
    """Получить список всех кастомных полей задач."""
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {PLANFIX_TOKEN}"}
        response = await client.get(
            f"{PLANFIX_BASE_URL.rstrip('/')}/customfield/task",
            headers=headers,
            params={"fields": "id,name,names,type"},
        )
        if response.status_code >= 400:
            print(f"❌ Ошибка получения кастомных полей: {response.status_code}")
            print(response.text)
            return []
        data = response.json()
        return data.get("customFields", [])


async def get_task_template_by_id(template_id: int):
    """Получить конкретный шаблон задачи по ID."""
    templates = await get_task_templates()
    for template in templates:
        if int(template.get("id")) == int(template_id):
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
    print("🔍 Получение списка всех кастомных полей задач...")
    all_fields = await get_all_task_custom_fields()
    
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
        custom_fields = template.get("customFields", [])

        # Показать только нужные шаблоны
        if template_ids_to_show and template_id not in template_ids_to_show:
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




