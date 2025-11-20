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
                        ],
                    }
                ]
            },
        )
        router.get("contact/").respond(200, json={"contacts": []})
        create_route = router.post("contact/").respond(200, json={"id": 123})

        response = await client.ensure_contact(contact_data)

        assert response["id"] == 123
        assert create_route.called

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
        router.get("contact/").respond(
            200,
            json={"contacts": [{"id": 321}]},
        )
        update_route = router.put("contact/321").respond(200, json={"id": 321})

        response = await client.ensure_contact(contact_data, update_existing=True)

        assert response["id"] == 321
        assert update_route.called

    await client.close()


