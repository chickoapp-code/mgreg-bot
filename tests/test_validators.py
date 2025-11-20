from datetime import date

import pytest

from bot.services.validators import (
    ValidationException,
    normalize_phone,
    parse_birthdate,
    validate_city,
    validate_name,
)


@pytest.mark.parametrize(
    "input_value,expected",
    [
        ("+7 (926) 000-00-00", "+79260000000"),
        ("89260000000", "+79260000000"),
        ("+1-202-555-0100", "+12025550100"),
    ],
)
def test_normalize_phone_success(input_value, expected):
    assert normalize_phone(input_value) == expected


@pytest.mark.parametrize("input_value", ["123", "++7999", "", None])
def test_normalize_phone_invalid(input_value):
    with pytest.raises(ValidationException):
        normalize_phone(input_value or "")


def test_parse_birthdate_success():
    assert parse_birthdate("01.01.2000") == date(2000, 1, 1)
    assert parse_birthdate("2000-01-01") == date(2000, 1, 1)


@pytest.mark.parametrize("input_value", ["32.01.2000", "2000/01/01", "", None])
def test_parse_birthdate_invalid(input_value):
    with pytest.raises(ValidationException):
        parse_birthdate(input_value or "")


def test_validate_name_success():
    assert validate_name("Иван", "Имя") == "Иван"


@pytest.mark.parametrize("input_value", ["", "A", "@#$", None])
def test_validate_name_invalid(input_value):
    with pytest.raises(ValidationException):
        validate_name(input_value or "", "Имя")


def test_validate_city_success():
    assert validate_city("Москва") == "Москва"


@pytest.mark.parametrize("input_value", ["", " ", "A"])
def test_validate_city_invalid(input_value):
    with pytest.raises(ValidationException):
        validate_city(input_value)


