"""Validation helpers for user input."""

from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import ValidationError


PHONE_CLEAN_PATTERN = re.compile(r"\D+")
PHONE_VALID_PATTERN = re.compile(r"^\+?[1-9]\d{7,14}$")


class ValidationException(ValueError):
    """Custom validation error for user-facing messages."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def normalize_phone(raw_phone: str) -> str:
    """Return sanitized phone number in E.164 format."""

    if not raw_phone:
        raise ValidationException("Пожалуйста, укажи номер телефона.")

    digits = PHONE_CLEAN_PATTERN.sub("", raw_phone)

    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]

    if digits.startswith("7") and len(digits) == 11:
        digits = "+" + digits
    elif raw_phone.startswith("+"):
        digits = "+" + digits
    elif not digits.startswith("+"):
        digits = "+" + digits

    if not PHONE_VALID_PATTERN.fullmatch(digits):
        raise ValidationException(
            "Кажется, формат номера некорректен. Попробуй ещё раз, пожалуйста."
        )

    return digits


def parse_birthdate(value: str) -> date:
    """Parse birthdate ensuring reasonable age boundaries."""

    if not value:
        raise ValidationException("Укажи, пожалуйста, дату рождения.")

    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt).date()
            break
        except ValueError:
            continue
    else:  # no break
        raise ValidationException(
            "Не получилось распознать дату. Используй формат ДД.ММ.ГГГГ, пожалуйста."
        )

    today = date.today()
    age = today.year - parsed.year - ((today.month, today.day) < (parsed.month, parsed.day))

    if age < 10 or age > 120:
        raise ValidationException(
            "Похоже, дата рождения указана неверно. Проверь, пожалуйста, и попробуй снова."
        )

    return parsed


def validate_name(value: str, field_label: str) -> str:
    """Validate name-like fields for minimum length and characters."""

    if not value or len(value.strip()) < 2:
        raise ValidationException(
            f"{field_label} должно содержать хотя бы два символа. Попробуй ещё раз."
        )

    sanitized = value.strip()
    if not re.fullmatch(r"[\w\-\sЁёА-Яа-я]+", sanitized):
        raise ValidationException(
            f"{field_label} содержит недопустимые символы. Попробуй снова, пожалуйста."
        )

    return sanitized


def validate_city(value: str) -> str:
    """Validate city input."""

    if not value or len(value.strip()) < 2:
        raise ValidationException(
            "Напиши, пожалуйста, название города — хотя бы два символа."
        )

    return value.strip()

