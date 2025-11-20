"""Handlers implementing the guest registration flow."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.logging import get_logger
from bot.schemas import ContactData
from bot.services.planfix import PlanfixClient, PlanfixError
from bot.services.validators import (
    ValidationException,
    normalize_phone,
    parse_birthdate,
    validate_city,
    validate_name,
)
from bot.states import RegistrationStates


router = Router()
logger = get_logger(__name__)

BUTTON_REGISTER = "Зарегистрироваться как Тайный гость"
BUTTON_SHARE_CONTACT = "Поделиться контактом"

GENDERS = [
    "Мужской",
    "Женский",
    "Другой/Не хочу указывать!",
]


def contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BUTTON_SHARE_CONTACT, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def gender_keyboard() -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text=gender)] for gender in GENDERS]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)


def confirmation_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Подтвердить регистрацию", callback_data="confirm_registration")
    builder.button(text="Изменить данные", callback_data="change_registration")
    builder.adjust(1)
    return builder


def duplicate_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Обновить данные", callback_data="duplicate_update_yes")
    builder.button(text="Отмена", callback_data="duplicate_update_no")
    builder.adjust(1)
    return builder


def format_summary(data: dict) -> str:
    return (
        "Проверь, пожалуйста, данные:\n"
        f"Телефон: {data['phone']}\n"
        f"Фамилия: {data['last_name']}\n"
        f"Имя: {data['first_name']}\n"
        f"Отчество: {data.get('patronymic') or '—'}\n"
        f"Пол: {data['gender']}\n"
        f"Дата рождения: {data['birthdate']}\n"
        f"Город: {data['city']}"
    )


def build_contact_data(state_data: dict) -> ContactData:
    return ContactData(
        phone=state_data["phone"],
        last_name=state_data["last_name"],
        first_name=state_data["first_name"],
        patronymic=state_data.get("patronymic"),
        gender=state_data["gender"],
        birthdate=state_data["birthdate_obj"],
        city=state_data["city"],
        telegram_username=state_data.get("telegram_username"),
        telegram_id=state_data.get("telegram_id"),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(
        telegram_username=message.from_user.username if message.from_user else None,
        telegram_id=message.from_user.id if message.from_user else None,
    )
    await message.answer(
        "Привет! Я помогу твоей регистрации как Тайный гость — всё займёт пару минут.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=BUTTON_REGISTER)]],
            resize_keyboard=True,
        ),
    )


@router.message(F.text == BUTTON_REGISTER)
async def start_registration(message: Message, state: FSMContext) -> None:
    await state.set_state(RegistrationStates.waiting_for_phone)
    if message.from_user:
        await state.update_data(
            telegram_username=message.from_user.username,
            telegram_id=message.from_user.id,
        )
    await message.answer(
        "Поделись номером — нажми кнопку «Поделиться контактом» или введи вручную.",
        reply_markup=contact_keyboard(),
    )


@router.message(RegistrationStates.waiting_for_phone, F.contact)
async def handle_contact(message: Message, state: FSMContext) -> None:
    if not message.contact or not message.contact.phone_number:
        await message.answer("Не удалось получить номер. Попробуй ещё раз, пожалуйста.")
        return

    try:
        phone = normalize_phone(message.contact.phone_number)
    except ValidationException as exc:
        await message.answer(exc.message)
        return

    await state.update_data(phone=phone)
    await state.set_state(RegistrationStates.waiting_for_last_name)
    await message.answer(
        "Отлично! Теперь напиши, пожалуйста, фамилию.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(RegistrationStates.waiting_for_phone)
async def handle_phone_text(message: Message, state: FSMContext) -> None:
    try:
        phone = normalize_phone(message.text or "")
    except ValidationException as exc:
        await message.answer(exc.message)
        return

    await state.update_data(phone=phone)
    await state.set_state(RegistrationStates.waiting_for_last_name)
    await message.answer("Спасибо! Введи, пожалуйста, фамилию.", reply_markup=ReplyKeyboardRemove())


@router.message(RegistrationStates.waiting_for_last_name)
async def handle_last_name(message: Message, state: FSMContext) -> None:
    try:
        last_name = validate_name(message.text or "", "Фамилия")
    except ValidationException as exc:
        await message.answer(exc.message)
        return

    await state.update_data(last_name=last_name)
    await state.set_state(RegistrationStates.waiting_for_first_name)
    await message.answer("Отлично! Теперь укажи, пожалуйста, имя.")


@router.message(RegistrationStates.waiting_for_first_name)
async def handle_first_name(message: Message, state: FSMContext) -> None:
    try:
        first_name = validate_name(message.text or "", "Имя")
    except ValidationException as exc:
        await message.answer(exc.message)
        return

    await state.update_data(first_name=first_name)
    await state.set_state(RegistrationStates.waiting_for_patronymic)
    await message.answer("Если есть отчество — напиши его, иначе можешь отправить прочерк.")


@router.message(RegistrationStates.waiting_for_patronymic)
async def handle_patronymic(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    patronymic = value if value and value != "-" else ""
    await state.update_data(patronymic=patronymic)
    await state.set_state(RegistrationStates.waiting_for_gender)
    await message.answer(
        "Выбери, пожалуйста, пол.",
        reply_markup=gender_keyboard(),
    )


@router.message(RegistrationStates.waiting_for_gender)
async def handle_gender(message: Message, state: FSMContext) -> None:
    gender = (message.text or "").strip()
    if gender not in GENDERS:
        await message.answer("Выбери вариант из списка, пожалуйста.")
        return

    await state.update_data(gender=gender)
    await state.set_state(RegistrationStates.waiting_for_birthdate)
    await message.answer(
        "Укажи дату рождения в формате ДД.ММ.ГГГГ, пожалуйста.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(RegistrationStates.waiting_for_birthdate)
async def handle_birthdate(message: Message, state: FSMContext) -> None:
    try:
        birthdate = parse_birthdate(message.text or "")
    except ValidationException as exc:
        await message.answer(exc.message)
        return

    await state.update_data(
        birthdate=birthdate.strftime("%d.%m.%Y"),
        birthdate_obj=birthdate,
    )
    await state.set_state(RegistrationStates.waiting_for_city)
    await message.answer("Напиши, пожалуйста, город проживания.")


@router.message(RegistrationStates.waiting_for_city)
async def handle_city(message: Message, state: FSMContext) -> None:
    try:
        city = validate_city(message.text or "")
    except ValidationException as exc:
        await message.answer(exc.message)
        return

    await state.update_data(city=city)
    data = await state.get_data()
    await state.set_state(RegistrationStates.confirmation)
    await message.answer(
        format_summary(data),
        reply_markup=confirmation_keyboard().as_markup(),
    )


@router.callback_query(RegistrationStates.confirmation, F.data == "change_registration")
async def change_registration(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(RegistrationStates.waiting_for_last_name)
    await callback.message.answer("Хорошо, начнём с фамилии. Напиши, пожалуйста, снова.")


@router.callback_query(RegistrationStates.confirmation, F.data == "confirm_registration")
async def confirm_registration(
    callback: CallbackQuery,
    state: FSMContext,
    bot_data: dict,
) -> None:
    await callback.answer()
    data = await state.get_data()
    contact_data = build_contact_data(data)

    client: PlanfixClient | None = bot_data.get("planfix_client")
    if client is None:
        logger.error("planfix_client_not_initialized")
        await callback.message.answer(
            "Произошла внутренняя ошибка. Пожалуйста, попробуй позже.",
        )
        return
    try:
        existing = await client.list_contacts_by_phone(contact_data.phone)
    except PlanfixError as exc:
        logger.error("planfix_search_failed", error=str(exc))
        await callback.message.answer(
            "Упс — временная проблема. Я попробую ещё раз через несколько секунд.",
        )
        return

    if existing:
        existing_id = int(existing[0]["id"])
        await state.update_data(existing_contact_id=existing_id)
        await state.set_state(RegistrationStates.duplicate_confirmation)
        await callback.message.answer(
            "Контакт с таким номером уже зарегистрирован. Обновить данные?",
            reply_markup=duplicate_keyboard().as_markup(),
        )
        return

    await _create_contact(callback, state, contact_data, bot_data)


@router.callback_query(
    RegistrationStates.duplicate_confirmation,
    F.data == "duplicate_update_no",
)
async def duplicate_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        "Хорошо, если решишь попробовать снова — просто напиши /start.",
    )


@router.callback_query(
    RegistrationStates.duplicate_confirmation,
    F.data == "duplicate_update_yes",
)
async def duplicate_update(
    callback: CallbackQuery,
    state: FSMContext,
    bot_data: dict,
) -> None:
    await callback.answer()
    data = await state.get_data()
    contact_data = build_contact_data(data)
    await _create_contact(callback, state, contact_data, bot_data, update_existing=True)


async def _create_contact(
    callback: CallbackQuery,
    state: FSMContext,
    contact_data: ContactData,
    bot_data: dict,
    *,
    update_existing: bool = False,
) -> None:
    client: PlanfixClient | None = bot_data.get("planfix_client")
    if client is None:
        logger.error("planfix_client_not_initialized")
        await callback.message.answer(
            "Произошла внутренняя ошибка. Пожалуйста, попробуй позже.",
        )
        return
    try:
        existing_id = None
        if update_existing:
            state_data = await state.get_data()
            existing_id = state_data.get("existing_contact_id")
        response = await client.ensure_contact(
            contact_data,
            update_existing=update_existing,
            existing_contact_id=existing_id,
        )
    except PlanfixError as exc:
        logger.error("planfix_contact_failed", error=str(exc))
        await callback.message.answer(
            "Упс — временная проблема. Я попробую ещё раз через несколько секунд.",
        )
        return

    contact_id = response.get("id") or response.get("contact", {}).get("id")
    if not contact_id and update_existing:
        contact_id = existing_id

    await callback.message.answer(
        "Спасибо — мы всё записали. Ты зарегистрирован(а). Ожидай уведомления в боте о задании.",
    )

    if contact_id:
        logger.info("planfix_contact_created", contact_id=contact_id)

        admin_chat_id = bot_data.get("admin_chat_id")
        admin_name = bot_data.get("admin_name")
        planfix_base_url = bot_data.get("planfix_base_url")

        if admin_chat_id:
            try:
                contact_url = None
                if planfix_base_url:
                    contact_url = f"{planfix_base_url.rstrip('/')}/contact/{contact_id}"

                message = (
                    "Новая регистрация Тайного гостя.\n"
                    f"Телефон: {contact_data.phone}\n"
                    f"Planfix ID: {contact_id}"
                )
                if contact_data.telegram_username:
                    username = contact_data.telegram_username
                    if not username.startswith("@"):
                        username = f"@{username}"
                    message += f"\nTelegram: {username}"
                elif contact_data.telegram_id:
                    message += f"\nTelegram ID: {contact_data.telegram_id}"
                if contact_url:
                    message += f"\nСсылка: {contact_url}"

                await callback.bot.send_message(int(admin_chat_id), message)
            except Exception as exc:  # pragma: no cover - logging safeguard
                logger.error("admin_notification_failed", error=str(exc))
        elif admin_name:
            await callback.message.answer(
                f"Если появятся вопросы — напиши {admin_name}.",
            )

    await state.clear()

