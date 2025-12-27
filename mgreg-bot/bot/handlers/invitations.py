"""Handlers for invitation accept/decline callbacks."""

from __future__ import annotations

import asyncio
from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.database import get_database
from bot.logging import get_logger
from bot.services.planfix import PlanfixClient, PlanfixError
import hashlib
import hmac

from bot.config import get_settings

router = Router()
logger = get_logger(__name__)


# Lock for concurrent accept handling
_accept_locks: dict[int, asyncio.Lock] = {}


def get_lock(task_id: int) -> asyncio.Lock:
    """Get or create lock for task."""
    if task_id not in _accept_locks:
        _accept_locks[task_id] = asyncio.Lock()
    return _accept_locks[task_id]


@router.callback_query(F.data.startswith("accept|"))
async def handle_accept(callback: CallbackQuery, bot_data: dict) -> None:
    """Handle accept invitation callback."""
    await callback.answer()

    try:
        _, task_id_str = callback.data.split("|", 1)
        task_id = int(task_id_str)
    except ValueError:
        await callback.message.answer("Ошибка: неверный формат данных.")
        return

    client: PlanfixClient | None = bot_data.get("planfix_client")
    if not client:
        logger.error("planfix_client_not_initialized")
        await callback.message.answer("Произошла внутренняя ошибка. Пожалуйста, попробуй позже.")
        return

    db = get_database()
    settings = bot_data.get("settings")

    # Get guest info
    guest_mapping = await db.fetch_one(
        "SELECT planfix_contact_id FROM guest_telegram_map WHERE telegram_id = ?",
        (callback.from_user.id,),
    )
    if not guest_mapping:
        await callback.message.answer(
            "Ошибка: не найдена связь с контактом в Planfix. Обратитесь к администратору."
        )
        return

    guest_planfix_id = guest_mapping["planfix_contact_id"]

    # Concurrent lock
    lock = get_lock(task_id)
    async with lock:
        # Check if task already has executor
        # Note: If task is not found in Planfix (e.g., it's deleted or doesn't exist yet),
        # we continue anyway as the task might have been created by automation and not yet available via API
        task = None
        try:
            task = await client.get_task(task_id, fields="id,assignees")
            assignees = task.get("assignees", [])
            if assignees:
                # Already assigned
                await callback.message.answer("Мы уже нашли тайного гостя для этой проверки. Спасибо!")
                await withdraw_invitations(task_id, callback.message.chat.id, callback.message.message_id, db)
                return
        except PlanfixError as e:
            # Log error but continue - task might not be available via API yet (created by automation)
            logger.warning("planfix_task_check_failed", task_id=task_id, error=str(e), message="Continuing anyway")
            # Don't return - allow assignment to proceed

        # Assign executor
        try:
            await client.set_task_executors(task_id, [guest_planfix_id])
            # Try to add comment (may fail if task not found, but that's ok)
            try:
                await client.add_task_comment(
                    task_id,
                    f"✅ Гость (ID: {guest_planfix_id}) принял приглашение и назначен исполнителем.",
                )
            except PlanfixError as comment_error:
                logger.warning("planfix_comment_add_failed_after_assignment", task_id=task_id, error=str(comment_error))

            # Update database
            await db.execute(
                "UPDATE tasks SET assigned_guest_id = ? WHERE task_id = ?",
                (guest_planfix_id, task_id),
            )

            # Send success message with WebApp button
            webapp_url = await generate_webapp_url(task_id, guest_planfix_id, settings, client=client)
            if webapp_url:
                from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Начать прохождение",
                                web_app=WebAppInfo(url=webapp_url),
                            )
                        ]
                    ]
                )
                await callback.message.answer(
                    "Отлично! Ты закреплён(а) за этой проверкой. Нажми «Начать прохождение», чтобы заполнить анкету.",
                    reply_markup=keyboard,
                )
            else:
                await callback.message.answer(
                    "Отлично! Ты закреплён(а) за этой проверкой. Свяжемся с тобой для дальнейших инструкций."
                )

            # Withdraw all invitations for this task
            await withdraw_all_invitations(
                task_id,
                callback.message.chat.id,
                callback.message.message_id,
                db,
                bot_instance=callback.bot,
            )

        except PlanfixError as e:
            logger.error("planfix_executor_assignment_failed", task_id=task_id, error=str(e))
            await callback.message.answer("Ошибка при назначении. Попробуй позже.")


@router.callback_query(F.data.startswith("decline|"))
async def handle_decline(callback: CallbackQuery, bot_data: dict) -> None:
    """Handle decline invitation callback."""
    await callback.answer()

    try:
        _, task_id_str = callback.data.split("|", 1)
        task_id = int(task_id_str)
    except ValueError:
        await callback.message.answer("Ошибка: неверный формат данных.")
        return

    db = get_database()

    # Mark invitation as withdrawn
    await db.execute(
        """
        UPDATE invitations 
        SET withdrawn_at = ? 
        WHERE task_id = ? AND telegram_id = ? AND message_id = ?
        """,
        (datetime.now().isoformat(), task_id, callback.from_user.id, callback.message.message_id),
    )

    await callback.message.answer("Спасибо, что ответил(а)! До встречи на следующей проверке!")

    # Delete invitation message
    try:
        await callback.message.delete()
    except Exception as e:
        logger.warning("invitation_delete_failed", error=str(e))

    # Check if all declined
    active_invitations = await db.fetch_all(
        """
        SELECT COUNT(*) as count FROM invitations 
        WHERE task_id = ? AND withdrawn_at IS NULL
        """,
        (task_id,),
    )
    if active_invitations and active_invitations[0]["count"] == 0:
        # Notify admin
        client: PlanfixClient | None = bot_data.get("planfix_client")
        admin_chat_id = bot_data.get("admin_chat_id")
        if client and admin_chat_id:
            try:
                bot = callback.bot
                await bot.send_message(
                    admin_chat_id,
                    f"⚠️ Все гости отказались от проверки задачи #{task_id}.",
                )
                await client.add_task_comment(task_id, "⚠️ Все приглашённые гости отказались от проверки.")
            except Exception as e:
                logger.error("admin_notification_failed", error=str(e))


async def withdraw_invitations(
    task_id: int,
    current_chat_id: int,
    current_message_id: int,
    db,
) -> None:
    """Withdraw invitation for current user."""
    await db.execute(
        """
        UPDATE invitations 
        SET withdrawn_at = ? 
        WHERE task_id = ? AND chat_id = ? AND message_id = ?
        """,
        (datetime.now().isoformat(), task_id, current_chat_id, current_message_id),
    )


async def withdraw_all_invitations(
    task_id: int,
    exclude_chat_id: int,
    exclude_message_id: int,
    db,
    bot_instance=None,
) -> None:
    """Withdraw all invitations for task except the accepted one."""
    # Get all invitation messages
    invitations = await db.fetch_all(
        """
        SELECT chat_id, message_id FROM invitations 
        WHERE task_id = ? AND withdrawn_at IS NULL
        AND NOT (chat_id = ? AND message_id = ?)
        """,
        (task_id, exclude_chat_id, exclude_message_id),
    )

    # Mark as withdrawn
    await db.execute(
        """
        UPDATE invitations 
        SET withdrawn_at = ? 
        WHERE task_id = ? AND withdrawn_at IS NULL
        AND NOT (chat_id = ? AND message_id = ?)
        """,
        (datetime.now().isoformat(), task_id, exclude_chat_id, exclude_message_id),
    )

    # Delete invitation messages
    if bot_instance:
        for inv in invitations:
            try:
                await bot_instance.delete_message(inv["chat_id"], inv["message_id"])
            except Exception as e:
                logger.warning("invitation_message_delete_failed", chat_id=inv["chat_id"], message_id=inv["message_id"], error=str(e))


def generate_webapp_signature(params: dict[str, str], secret: str) -> str:
    """Generate HMAC signature for WebApp URL."""
    sorted_params = sorted(params.items())
    query_string = "&".join(f"{k}={v}" for k, v in sorted_params)
    return hmac.new(
        secret.encode(),
        query_string.encode(),
        hashlib.sha256,
    ).hexdigest()


async def generate_webapp_url(task_id: int, guest_id: int, settings, client: PlanfixClient = None) -> str | None:
    """Generate WebApp URL with signature."""
    if not settings or not hasattr(settings, "webhook_base_url"):
        return None

    base_url = settings.webhook_base_url or "http://localhost:8001"
    
    # Determine form type from task (default to resto_a)
    form = "resto_a"
    if client:
        try:
            task = await client.get_task(task_id, fields="id,name,description,customFieldData")
            # Check custom fields or task name to determine form type
            task_name = task.get("name", "").lower()
            if "доставка" in task_name or "delivery" in task_name:
                form = "delivery_a"  # Default delivery form
            # Could also check custom fields for form type
        except Exception as e:
            logger.warning("form_type_determination_failed", task_id=task_id, error=str(e))

    params = {
        "taskId": str(task_id),
        "guestId": str(guest_id),
        "form": form,
        "ts": str(int(datetime.now().timestamp())),
    }
    sig = generate_webapp_signature(params, settings.webapp_hmac_secret)

    return f"{base_url}/webapp/start?taskId={task_id}&guestId={guest_id}&form={form}&sig={sig}&ts={params['ts']}"

