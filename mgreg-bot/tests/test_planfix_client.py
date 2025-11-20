import json
from datetime import date

import pytest
import respx
from httpx import Response

from bot.schemas import ContactData
from bot.services.planfix import PlanfixClient


@pytest.mark.asyncio
async def test_ensure_contact_creates_contact():
    client = PlanfixClient(
        base_url="https://example.planfix/rest/",
        token="token",
        template_id=413,
    )

    contact_data = ContactData(
        phone="+79260000000",
        last_name="Иванов",
        first_name="Иван",
        patronymic="",
        gender="Мужской",
        birthdate=date(1990, 1, 1),
        city="Москва",
        telegram_username="secret_guest",
        telegram_id=123456789,
    )

    async with respx.mock(base_url="https://example.planfix/rest/") as router:
        router.get("contact/templates").respond(
            200,
            json={
                "templates": [
                    {
                        "id": 413,
                        "customFields": [
                            {"id": 1, "label": "Город"},
                            {"id": 2, "label": "Пол"},
                            {"id": 3, "label": "Telegram"},
                        ],
                    }
                ]
            },
        )
        create_route = router.post("contact/").respond(200, json={"id": 123})

        response = await client.ensure_contact(contact_data)

        assert response["id"] == 123
        assert create_route.called

        sent_payload = json.loads(create_route.calls[0].request.content.decode())
        custom_fields = sent_payload.get("customFieldData", [])
        assert any(
            entry["value"] == "https://t.me/secret_guest"
            for entry in custom_fields
        )
        assert sent_payload.get("sourceObjectId") == "123456789"
        assert sent_payload.get("telegram") == "https://t.me/secret_guest"
        assert sent_payload.get("telegramId") == "123456789"

    await client.close()


@pytest.mark.asyncio
async def test_ensure_contact_updates_contact():
    client = PlanfixClient(
        base_url="https://example.planfix/rest/",
        token="token",
        template_id=413,
    )

    contact_data = ContactData(
        phone="+79260000000",
        last_name="Иванов",
        first_name="Иван",
        patronymic="",
        gender="Мужской",
        birthdate=date(1990, 1, 1),
        city="Москва",
        telegram_username="secret_guest",
        telegram_id=123456789,
    )

    async with respx.mock(base_url="https://example.planfix/rest/") as router:
        router.get("contact/templates").respond(
            200,
            json={
                "templates": [
                    {
                        "id": 413,
                        "customFields": [],
                    }
                ]
            },
        )
        update_route = router.post("contact/321").respond(200, json={"id": 321})

        response = await client.ensure_contact(
            contact_data,
            update_existing=True,
            existing_contact_id=321,
        )

        assert response["id"] == 321
        assert update_route.called

    await client.close()

