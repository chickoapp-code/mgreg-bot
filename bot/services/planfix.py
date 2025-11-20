"""Асинхронный клиент для работы с Planfix REST API."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import httpx
from tenacity import AsyncRetrying, RetryError, retry_if_exception_type, stop_after_attempt, wait_exponential

from bot.logging import get_logger
from bot.schemas import ContactData, PlanfixContactPayload


logger = get_logger(__name__)


class PlanfixError(Exception):
    """Базовое исключение для ошибок Planfix."""


class PlanfixClient:
    """HTTP-клиент для операций с контактами в Planfix."""

    def __init__(
        self,
        base_url: str,
        token: str,
        template_id: int,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._token = token
        self._template_id = template_id
        self._timeout = timeout
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token}"}

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type((httpx.RequestError, PlanfixError)),
            reraise=True,
        ):
            with attempt:
                response = await self._client.request(
                    method=method,
                    url=endpoint,
                    json=json,
                    params=params,
                    headers=headers,
                )

                if response.status_code >= 500:
                    logger.warning(
                        "planfix_request_retry",
                        status=response.status_code,
                        endpoint=endpoint,
                    )
                    raise PlanfixError("Server error")

                if response.status_code >= 400:
                    logger.error(
                        "planfix_request_failed",
                        status=response.status_code,
                        body=response.text,
                        endpoint=endpoint,
                    )
                    raise PlanfixError(
                        f"Planfix API error: {response.status_code}"
                    )

                return response.json()

        raise RetryError("Unreachable")

    async def get_contact_template(self) -> Dict[str, Any]:
        logger.info("planfix_template_fetch", template_id=self._template_id)
        response = await self._request(
            "GET",
            "contact/templates",
        )
        templates = response.get("templates", [])
        for template in templates:
            if int(template.get("id")) == int(self._template_id):
                return template
        raise PlanfixError(f"Template {self._template_id} not found")

    async def list_contacts_by_phone(self, phone: str) -> list[dict[str, Any]]:
        logger.info("planfix_contact_search", phone=phone)
        response = await self._request(
            "GET",
            "contact/",
            params={"filter[phone]": phone},
        )
        return response.get("contacts", [])

    async def create_contact(self, contact: PlanfixContactPayload) -> Dict[str, Any]:
        payload = contact.model_dump(mode="json", exclude_none=True)
        logger.info("planfix_contact_create", template_id=self._template_id)
        response = await self._request(
            "POST",
            "contact/",
            json=payload,
        )
        return response

    async def update_contact(self, contact_id: int, contact: PlanfixContactPayload) -> Dict[str, Any]:
        payload = contact.model_dump(mode="json", exclude_none=True)
        logger.info("planfix_contact_update", contact_id=contact_id)
        response = await self._request(
            "PUT",
            f"contact/{contact_id}",
            json=payload,
        )
        return response

    async def ensure_contact(
        self,
        data: ContactData,
        *,
        update_existing: bool = False,
    ) -> Dict[str, Any]:
        """Создать или обновить контакт на основе данных пользователя и шаблона.

        1) Получаем шаблон для маппинга кастомных полей.
        2) Ищем контакт по телефону.
        3) Создаём новый или обновляем существующий (если update_existing=True).
        """
        template = await self.get_contact_template()
        payload = PlanfixContactPayload.from_contact_data(
            data,
            template=template,
            template_id=self._template_id,
        )
        existing = await self.list_contacts_by_phone(data.phone)
        if existing and update_existing:
            contact_id = int(existing[0]["id"])
            return await self.update_contact(contact_id, payload)
        return await self.create_contact(payload)


async def create_planfix_client(settings) -> PlanfixClient:
    client = PlanfixClient(
        base_url=str(settings.planfix_base_url),
        token=settings.planfix_token,
        template_id=settings.planfix_template_id,
    )
    return client

