"""Состояния FSM для сценария регистрации гостя."""

from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    """Список состояний мастера регистрации гостя."""

    waiting_for_phone = State()
    waiting_for_last_name = State()
    waiting_for_first_name = State()
    waiting_for_patronymic = State()
    waiting_for_gender = State()
    waiting_for_birthdate = State()
    waiting_for_city = State()
    confirmation = State()
    duplicate_confirmation = State()

