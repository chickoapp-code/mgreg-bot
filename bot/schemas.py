"""Схемы данных для взаимодействия с Planfix."""

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


class PlanfixContactPayload(BaseModel):
    templateId: int = Field(alias="templateId")
    lastName: str | None = None
    firstName: str | None = None
    patronymic: str | None = None
    fullName: str | None = None
    phone: str | None = None
    gender: str | None = None
    birthday: str | None = None
    city: str | None = None
    customFields: Dict[str, Any] | None = None

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
        """Построить тело запроса к Planfix из данных пользователя и шаблона."""
        full_name = " ".join(
            filter(None, [data.last_name, data.first_name, data.patronymic])
        )

        gender_map = {
            "Мужской": "male",
            "Женский": "female",
            "Другой/Не хочу указывать": "other",
        }

        custom_fields: Dict[str, Any] = {}

        for field in template.get("customFields", []):
            field_label = field.get("label") or field.get("name")
            field_id = field.get("id")
            if not field_id:
                continue
            if field_label == "Город" and data.city:
                custom_fields[str(field_id)] = data.city
            if field_label == "Пол" and data.gender:
                custom_fields[str(field_id)] = gender_map.get(data.gender, data.gender)

        payload = cls(
            templateId=template_id,
            lastName=data.last_name,
            firstName=data.first_name,
            patronymic=data.patronymic or "",
            fullName=full_name,
            phone=data.phone,
            gender=gender_map.get(data.gender, data.gender),
            birthday=data.birthdate.isoformat(),
            city=data.city,
            customFields=custom_fields or None,
        )

        return payload

