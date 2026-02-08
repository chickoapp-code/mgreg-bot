#!/usr/bin/env python3
"""Скрипт для получения всех статусов задач из Planfix.

Использование:
    python get_task_statuses.py

Требуется в .env файле:
    PLANFIX_BASE_URL=https://your-account.planfix.ru/rest/
    PLANFIX_TOKEN=your_service_token_here
    PLANFIX_TASK_TEMPLATE_IDS=83960  # опционально: показать процесс для этого шаблона
"""

import asyncio
import os
from dotenv import load_dotenv
import httpx

load_dotenv()

PLANFIX_BASE_URL = os.getenv("PLANFIX_BASE_URL", "https://conquest.planfix.ru/rest/")
PLANFIX_TOKEN = os.getenv("PLANFIX_TOKEN")
PLANFIX_TASK_TEMPLATE_IDS = os.getenv("PLANFIX_TASK_TEMPLATE_IDS", "")


async def get_task_processes() -> list:
    """GET /process/task — список процессов задач."""
    url = f"{PLANFIX_BASE_URL.rstrip('/')}/process/task"
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {PLANFIX_TOKEN}"}
        response = await client.get(
            url,
            headers=headers,
            params={"fields": "id,name"},
        )
        if response.status_code >= 400:
            print(f"❌ Ошибка GET {url}: {response.status_code}")
            print(response.text[:500])
            return []
        data = response.json()
        return data.get("processes") or data.get("process") or []


async def get_statuses_for_process(process_id: int) -> list:
    """GET /process/task/{id}/statuses — статусы для процесса."""
    url = f"{PLANFIX_BASE_URL.rstrip('/')}/process/task/{process_id}/statuses"
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {PLANFIX_TOKEN}"}
        response = await client.get(
            url,
            headers=headers,
            params={"fields": "id,name,color,isActive,texts"},
        )
        if response.status_code >= 400:
            print(f"❌ Ошибка GET {url}: {response.status_code}")
            return []
        data = response.json()
        return data.get("statuses") or data.get("status") or []


async def get_task_templates() -> list:
    """Список шаблонов задач (для привязки к процессу)."""
    url = f"{PLANFIX_BASE_URL.rstrip('/')}/task/templates"
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {PLANFIX_TOKEN}"}
        response = await client.get(
            url,
            headers=headers,
            params={"fields": "id,name,processId"},
            timeout=30.0,
        )
        if response.status_code >= 400:
            return []
        data = response.json()
        return data.get("templates", [])


def _status_name(s: dict) -> str:
    """Название статуса (RU приоритет)."""
    texts = s.get("texts") or []
    for t in texts:
        if t.get("lang") == "Ru":
            return t.get("name") or s.get("name") or "—"
    return s.get("name") or "—"


async def main() -> None:
    """Основная функция."""
    if not PLANFIX_TOKEN:
        print("❌ Ошибка: PLANFIX_TOKEN не указан в .env")
        return

    print("=" * 80)
    print("📋 Статусы задач Planfix")
    print("=" * 80)
    print()

    # Шаблоны → processId (для подсказки)
    template_ids = []
    if PLANFIX_TASK_TEMPLATE_IDS:
        template_ids = [int(x.strip()) for x in PLANFIX_TASK_TEMPLATE_IDS.split(",") if x.strip()]
        print(f"📌 Шаблоны задач из PLANFIX_TASK_TEMPLATE_IDS: {template_ids}\n")

    templates = await get_task_templates()
    template_to_process: dict[int, int] = {}
    for t in templates:
        tid = int(t.get("id", 0))
        pid = t.get("processId")
        if pid is not None:
            template_to_process[tid] = int(pid)

    # Процессы
    processes = await get_task_processes()
    if not processes:
        print("⚠️  Процессы задач не найдены")
        return

    print(f"✅ Найдено процессов: {len(processes)}\n")

    for proc in sorted(processes, key=lambda p: int(p.get("id", 0))):
        proc_id = int(proc.get("id", 0))
        proc_name = proc.get("name") or "—"
        statuses = await get_statuses_for_process(proc_id)

        # Помечаем процесс, если он привязан к нашему шаблону
        is_relevant = proc_id in template_to_process.values()
        if template_ids and any(template_to_process.get(tid) == proc_id for tid in template_ids):
            is_relevant = True

        header = f"📌 Процесс: {proc_name} (ID: {proc_id})"
        if is_relevant and template_ids:
            header += "  ← используется вашим шаблоном"
        print(header)
        print("-" * 80)
        print(f"{'ID':<10} {'Название (RU)':<45} {'Цвет':<12} {'Активен'}")
        print("-" * 80)

        for s in sorted(statuses, key=lambda x: int(x.get("id", 0))):
            sid = s.get("id")
            name = _status_name(s)
            color = s.get("color") or "—"
            active = "да" if s.get("isActive", True) else "нет"
            print(f"{sid:<10} {name:<45} {color:<12} {active}")
        print()

    print("=" * 80)
    print("📝 Рекомендации для .env")
    print("=" * 80)
    print()
    print("# Статус «Выполнено» после отправки анкеты")
    print("STATUS_DONE_ID=XXX")
    print()
    print("# Статус «Отменено» (если нужно)")
    print("STATUS_CANCELLED_ID=XXX")
    print()
    print("Подставьте ID нужных статусов из таблицы выше.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
