"""FSM states for guest registration flow."""

from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    """States for the guest registration wizard."""

    waiting_for_phone = State()
    waiting_for_last_name = State()
    waiting_for_first_name = State()
    waiting_for_patronymic = State()
    waiting_for_gender = State()
    waiting_for_birthdate = State()
    waiting_for_city = State()
    confirmation = State()
    duplicate_confirmation = State()

