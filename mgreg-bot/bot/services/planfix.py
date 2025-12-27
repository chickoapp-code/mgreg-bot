"""Async client for interacting with Planfix REST API."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import httpx
from tenacity import AsyncRetrying, RetryError, retry_if_exception_type, stop_after_attempt, wait_exponential

from bot.logging import get_logger
from bot.schemas import ContactData, PlanfixContactPayload


logger = get_logger(__name__)


class PlanfixError(Exception):
    """Base exception for Planfix errors."""
    
    def __init__(self, message: str, status_code: int = 0, body: str = ""):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.body = body
    
    def is_task_not_found(self) -> bool:
        """Check if error is due to task not found."""
        if self.status_code == 400:
            body_lower = self.body.lower()
            return "not found" in body_lower or '"code":1000' in body_lower or '"code": 1000' in body_lower
        return False


class PlanfixClient:
    """HTTP client for Planfix operations."""

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
        data: Optional[Dict[str, Any]] = None,
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
                    data=data,
                    headers=headers,
                )

                if response.status_code >= 500:
                    logger.warning(
                        "planfix_request_retry",
                        status=response.status_code,
                        endpoint=endpoint,
                        body=response.text,
                    )
                    raise PlanfixError("Server error", status_code=response.status_code, body=response.text)

                if response.status_code >= 400:
                    error_body = response.text
                    logger.error(
                        "planfix_request_failed",
                        status=response.status_code,
                        body=error_body,
                        endpoint=endpoint,
                    )
                    raise PlanfixError(
                        f"Planfix API error: {response.status_code}",
                        status_code=response.status_code,
                        body=error_body,
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
        payload = {
            "offset": 0,
            "pageSize": 100,
            "fields": "id,name,midname,lastname,phones",
            "filters": [
                {
                    "type": 4003,  # phone filter
                    "operator": "equal",
                    "value": phone,
                }
            ],
        }
        response = await self._request(
            "POST",
            "contact/list",
            json=payload,
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
            "POST",
            f"contact/{contact_id}",
            json=payload,
        )
        return response

    async def ensure_contact(
        self,
        data: ContactData,
        *,
        update_existing: bool = False,
        existing_contact_id: int | None = None,
    ) -> Dict[str, Any]:
        template = await self.get_contact_template()
        payload = PlanfixContactPayload.from_contact_data(
            data,
            template=template,
            template_id=self._template_id,
        )
        if update_existing:
            contact_id = existing_contact_id
            if contact_id is None:
                existing = await self.list_contacts_by_phone(data.phone)
                if not existing:
                    raise PlanfixError("Contact not found for update")
                contact_id = int(existing[0]["id"])
            return await self.update_contact(contact_id, payload)
        return await self.create_contact(payload)

    async def get_task(self, task_id: int, fields: Optional[str] = None) -> Dict[str, Any]:
        """Get task by ID."""
        logger.info("planfix_task_get", task_id=task_id)
        params = {}
        if fields:
            params["fields"] = fields
        response = await self._request("GET", f"task/{task_id}", params=params)
        return response.get("task", response)

    async def update_task(
        self,
        task_id: int,
        *,
        status: Optional[int] = None,
        custom_field_data: Optional[list[Dict[str, Any]]] = None,
        assignees: Optional[Dict[str, Any]] = None,
        silent: bool = False,
    ) -> Dict[str, Any]:
        """Update task."""
        logger.info("planfix_task_update", task_id=task_id, status=status)
        payload: Dict[str, Any] = {}
        if status is not None:
            payload["status"] = {"id": status}
        if custom_field_data is not None:
            payload["customFieldData"] = custom_field_data
        if assignees is not None:
            payload["assignees"] = assignees

        params = {}
        if silent:
            params["silent"] = "true"

        response = await self._request("POST", f"task/{task_id}", json=payload, params=params)
        return response

    async def add_task_comment(
        self,
        task_id: int,
        text: str,
        *,
        silent: bool = False,
    ) -> Dict[str, Any]:
        """Add comment to task."""
        logger.info("planfix_task_comment_add", task_id=task_id)
        # Planfix API expects "description" field, not "text"
        payload = {"description": text}
        params = {}
        if silent:
            params["silent"] = "true"
        response = await self._request("POST", f"task/{task_id}/comments/", json=payload, params=params)
        return response

    async def upload_file_to_task(
        self,
        task_id: int,
        file_path: str,
        *,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload file to task."""
        logger.info("planfix_task_file_upload", task_id=task_id, file_path=file_path)
        # Read file and upload
        import aiofiles
        async with aiofiles.open(file_path, "rb") as f:
            file_content = await f.read()
            files = {"file": (Path(file_path).name, file_content, "application/octet-stream")}
            data: Dict[str, Any] = {}
            if description:
                data["description"] = description

            # Use multipart/form-data for file upload
            headers = {"Authorization": f"Bearer {self._token}"}
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._base_url}task/{task_id}/files",
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=self._timeout,
                )
                if response.status_code >= 400:
                    raise PlanfixError(
                        f"File upload failed: {response.status_code}",
                        status_code=response.status_code,
                        body=response.text,
                    )
                return response.json()

    async def upload_file_from_url(
        self,
        task_id: int,
        file_url: str,
        *,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload file to task from URL."""
        logger.info("planfix_task_file_upload_url", task_id=task_id, file_url=file_url)
        payload: Dict[str, Any] = {"url": file_url}
        if description:
            payload["description"] = description
        response = await self._request("POST", f"task/{task_id}/files/from-url", json=payload)
        return response

    async def set_task_executors(
        self,
        task_id: int,
        executor_contact_ids: list[int],
        *,
        silent: bool = False,
    ) -> Dict[str, Any]:
        """Set task executors (assignees).
        
        According to Planfix API, assignees should be in format:
        {
          "users": [{"id": "contact:1"}, ...],
          "groups": [...]
        }
        """
        logger.info("planfix_task_set_executors", task_id=task_id, executors=executor_contact_ids)
        # Planfix API expects assignees as object with "users" array
        # Contact IDs should be formatted as "contact:ID" or just ID as integer
        assignees = {
            "users": [{"id": f"contact:{cid}"} for cid in executor_contact_ids]
        }
        return await self.update_task(task_id, assignees=assignees, silent=silent)

    async def get_contact(self, contact_id: int) -> Dict[str, Any]:
        """Get contact by ID."""
        logger.info("planfix_contact_get", contact_id=contact_id)
        response = await self._request("GET", f"contact/{contact_id}")
        return response.get("contact", response)


