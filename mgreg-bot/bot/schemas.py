"""Data schemas for Planfix interactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict

from pydantic import BaseModel, Field


@dataclass
class ContactData:
    phone: str
    last_name: str
    first_name: str
    patronymic: str | None
    gender: str
    birthdate: date
    city: str
    telegram_username: str | None = None
    telegram_id: int | None = None


class PlanfixContactPayload(BaseModel):
    template: Dict[str, int]
    lastname: str
    name: str
    midname: str | None = None
    gender: str | None = None
    address: str | None = None
    birthDate: Dict[str, str] | None = None
    phones: list[Dict[str, Any]]
    customFieldData: list[Dict[str, Any]] | None = None
    sourceObjectId: str | None = None
    sourceDataVersion: str | None = None
    description: str | None = None
    isCompany: bool | None = None
    isDeleted: bool | None = None
    telegram: str | None = None
    telegramId: str | None = None

    model_config = {
        "populate_by_name": True,
        "alias_generator": None,
        "extra": "allow",
    }

    @classmethod
    def from_contact_data(
        cls,
        data: ContactData,
        *,
        template: dict,
        template_id: int,
    ) -> "PlanfixContactPayload":
        gender_map = {
            "Мужской": "Male",
            "Женский": "Female",
            "Другой/Не хочу указывать": "Other",
        }

        custom_fields: list[Dict[str, Any]] = []

        for field in template.get("customFields", []):
            field_label = field.get("label") or field.get("name")
            field_id = field.get("id")
            if not field_id:
                continue
            label_lower = field_label.lower() if isinstance(field_label, str) else ""
            if field_label == "Город" and data.city:
                custom_fields.append({"field": {"id": int(field_id)}, "value": data.city})
            if label_lower == "пол" and data.gender:
                custom_fields.append(
                    {
                        "field": {"id": int(field_id)},
                        "value": gender_map.get(data.gender, data.gender),
                    }
                )
            if data.telegram_username:
                username_clean = data.telegram_username.lstrip("@")
                username_value = f"https://t.me/{username_clean}"
                if (
                    "telegram" in label_lower and "id" not in label_lower
                    or "телеграм" in label_lower and "id" not in label_lower
                    or ("ник" in label_lower and ("тел" in label_lower or "tg" in label_lower))
                ):
                    custom_fields.append(
                        {
                            "field": {"id": int(field_id)},
                            "value": username_value,
                        }
                    )
            if data.telegram_id and ("telegram" in label_lower and "id" in label_lower):
                custom_fields.append(
                    {
                        "field": {"id": int(field_id)},
                        "value": str(data.telegram_id),
                    }
                )

        phones = [{"number": data.phone, "type": 1}]

        birth_date = {
            "date": data.birthdate.strftime("%d-%m-%Y"),
        }

        source_object_id = str(data.telegram_id) if data.telegram_id is not None else None
        telegram_link: str | None = None
        if data.telegram_username:
            username_clean = data.telegram_username.lstrip("@")
            telegram_link = f"https://t.me/{username_clean}"

        return cls(
            template={"id": template_id},
            lastname=data.last_name,
            name=data.first_name,
            midname=data.patronymic or "",
            gender=gender_map.get(data.gender, data.gender),
            address=data.city,
            birthDate=birth_date,
            phones=phones,
            customFieldData=custom_fields or None,
            isCompany=False,
            isDeleted=False,
            sourceObjectId=source_object_id,
            telegram=telegram_link,
            telegramId=str(data.telegram_id) if data.telegram_id is not None else None,
        )

