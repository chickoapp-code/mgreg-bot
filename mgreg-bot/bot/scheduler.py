"""Scheduler for deadline jobs and retry executor assignments."""

from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from bot.config import get_settings
from bot.database import get_database
from bot.logging import get_logger
from bot.services.planfix import PlanfixClient, PlanfixError

logger = get_logger(__name__)
settings = get_settings()
scheduler = AsyncIOScheduler()


async def check_task_deadline(task_id: int, client: PlanfixClient) -> None:
    """Check if task deadline has passed and form was not submitted."""
    """Check if task deadline passed and handle accordingly."""
    db = get_database()

    # Check if form was completed
    session = await db.fetch_one(
        """
        SELECT completed_at FROM form_sessions 
        WHERE task_id = ? AND completed_at IS NOT NULL
        LIMIT 1
        """,
        (task_id,),
    )

    if session and session["completed_at"]:
        logger.info("task_deadline_check_skipped_completed", task_id=task_id)
        return

    # Task not completed - cancel it
    try:
        if settings.status_cancelled_id:
            await client.update_task(int(task_id), status=settings.status_cancelled_id)
            await client.add_task_comment(
                int(task_id),
                "⏰ Дедлайн истёк. Проверка не была пройдена. Задача отменена.",
            )
            logger.info("task_deadline_cancelled", task_id=task_id)

            # Notify admin (bot instance should be set via webhook_server)
            from bot.webhook_server import bot_instance
            admin_chat_id = settings.admin_chat_id
            if admin_chat_id and bot_instance:
                try:
                    await bot_instance.send_message(
                        admin_chat_id,
                        f"⏰ Дедлайн истёк для задачи #{task_id}. Проверка не была пройдена. Задача отменена.",
                    )
                except Exception as e:
                    logger.error("admin_deadline_notification_failed", error=str(e))

    except PlanfixError as e:
        logger.error("task_deadline_check_failed", task_id=task_id, error=str(e))


async def schedule_deadline_check(task_id: int, deadline_str: str, client: PlanfixClient) -> None:
    """Schedule deadline check for task.
    
    Args:
        task_id: Task ID (must be int)
        deadline_str: Deadline in ISO format (YYYY-MM-DD) or Planfix format (DD-MM-YYYY)
        client: Planfix client instance
    """
    try:
        # Parse deadline - try ISO format first
        try:
            deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
        except ValueError:
            # Try Planfix format (DD-MM-YYYY)
            try:
                deadline = datetime.strptime(deadline_str, "%d-%m-%Y")
            except ValueError:
                # Try DD.MM.YYYY format
                deadline = datetime.strptime(deadline_str, "%d.%m.%Y")
        
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)

        # Schedule job
        scheduler.add_job(
            check_task_deadline,
            trigger=DateTrigger(run_date=deadline),
            args=[task_id, client],
            id=f"deadline_{task_id}",
            replace_existing=True,
        )
        logger.info("deadline_scheduled", task_id=task_id, deadline=deadline.isoformat())
    except Exception as e:
        logger.error("deadline_schedule_failed", task_id=task_id, error=str(e))


def start_scheduler() -> None:
    """Start the scheduler."""
    if not scheduler.running:
        scheduler.start()
        logger.info("scheduler_started")
        
        # Schedule periodic retry of executor assignments (every 30 seconds)
        scheduler.add_job(
            retry_executor_assignments,
            trigger=IntervalTrigger(seconds=30),
            id="retry_executor_assignments",
            replace_existing=True,
        )
        logger.info("retry_executor_assignments_job_scheduled")
    else:
        logger.info("scheduler_already_running")


async def retry_executor_assignments() -> None:
    """Retry executor assignments for tasks that were reserved but executor not yet assigned in Planfix.
    
    This function handles cases where:
    1. User accepted invitation, but task was not yet available via Planfix REST API
    2. Task ID was received from Planfix webhook and saved to database
    3. Task becomes available later, and we need to assign executor
    """
    db = get_database()
    
    # Get planfix_client from webhook_server
    from bot.webhook_server import planfix_client
    if not planfix_client:
        logger.warning("planfix_client_not_available_for_retry")
        return
    
    # Find tasks with assigned_guest_id but check if executor is actually assigned in Planfix
    # Use nomber field for API calls (task number from webhook), not task_id
    tasks = await db.fetch_all(
        """
        SELECT task_id, nomber, assigned_guest_id 
        FROM tasks 
        WHERE assigned_guest_id IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 50
        """
    )
    
    if not tasks:
        return
    
    logger.info(
        "retry_executor_assignments_started",
        count=len(tasks),
        note="Checking tasks with assigned_guest_id. Task IDs come from Planfix webhooks."
    )
    
    for task_row in tasks:
        # Use nomber field for API calls (task number from webhook), not task_id
        # sqlite3.Row doesn't have .get() method, use direct access with try/except
        try:
            task_nomber = task_row["nomber"]
            if task_nomber:
                task_nomber = str(task_nomber)
            else:
                task_nomber = None
        except (KeyError, TypeError):
            task_nomber = None
        
        if not task_nomber:
            # Fallback to task_id if nomber is not available (for backward compatibility)
            task_nomber = str(task_row["task_id"])
            logger.warning("nomber_not_found_using_task_id", task_id=task_row["task_id"])
        
        guest_planfix_id = task_row["assigned_guest_id"]
        
        try:
            # Check if executor is already assigned in Planfix
            # Use nomber (task number from webhook) for API calls
            task = await planfix_client.get_task(task_nomber, fields="id,assignees")
            assignees = task.get("assignees", {})
            
            # Handle both formats: object with "users" field or list
            if isinstance(assignees, dict):
                users = assignees.get("users", [])
            elif isinstance(assignees, list):
                users = assignees
            else:
                users = []
            
            # Check if our guest is already in assignees
            # User ID can be in formats: "contact:427", "user:5", or just "427"
            guest_assigned = False
            for user in users:
                user_id = str(user.get("id", ""))
                # Check various formats
                if (
                    user_id.endswith(f":{guest_planfix_id}") or
                    user_id == str(guest_planfix_id) or
                    user_id == f"contact:{guest_planfix_id}"
                ):
                    guest_assigned = True
                    break
            
            if guest_assigned:
                # Already assigned, skip
                logger.debug("executor_already_assigned", task_nomber=task_nomber, guest_id=guest_planfix_id)
                continue
            
            # Try to assign executor
            logger.info("retry_executor_assignment", task_nomber=task_nomber, guest_id=guest_planfix_id)
            await planfix_client.set_task_executors(task_nomber, [guest_planfix_id])
            
            # Try to add comment
            try:
                await planfix_client.add_task_comment(
                    task_nomber,
                    f"✅ Гость (ID: {guest_planfix_id}) принял приглашение и назначен исполнителем.",
                )
            except PlanfixError as comment_error:
                logger.warning("retry_comment_add_failed", task_nomber=task_nomber, error=str(comment_error))

            # Set status to 113 "Ожидаем визит", then 114 "Ожидаем анкету"
            from bot.config import get_settings
            s = get_settings()
            if s.status_waiting_visit_id:
                try:
                    await planfix_client.update_task(task_nomber, status=s.status_waiting_visit_id)
                except PlanfixError as e:
                    logger.warning("retry_status_113_failed", task_nomber=task_nomber, error=str(e))
            if s.status_waiting_form_id:
                try:
                    await planfix_client.update_task(task_nomber, status=s.status_waiting_form_id)
                except PlanfixError as e:
                    logger.warning("retry_status_114_failed", task_nomber=task_nomber, error=str(e))

            logger.info("retry_executor_assignment_success", task_nomber=task_nomber, guest_id=guest_planfix_id)
            
            # Notify user via Telegram if bot instance is available
            from bot.webhook_server import bot_instance
            if bot_instance:
                try:
                    # Get telegram_id from guest_planfix_id
                    guest_mapping = await db.fetch_one(
                        "SELECT telegram_id FROM guest_telegram_map WHERE planfix_contact_id = ?",
                        (guest_planfix_id,),
                    )
                    if guest_mapping:
                        telegram_id = guest_mapping["telegram_id"]
                        # Try to get WebApp URL
                        from bot.handlers.invitations import generate_webapp_url
                        # Use task_id from DB for webapp (it expects task_id, not nomber)
                        task_id_for_webapp = task_row["task_id"]
                        webapp_url = await generate_webapp_url(task_id_for_webapp, guest_planfix_id, settings, client=planfix_client)
                        
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
                            msg = await bot_instance.send_message(
                                telegram_id,
                                "✅ Отлично! Ты теперь назначен(а) исполнителем задачи. Нажми «Начать прохождение», чтобы заполнить анкету.",
                                reply_markup=keyboard,
                            )
                        else:
                            msg = await bot_instance.send_message(
                                telegram_id,
                                "✅ Отлично! Ты теперь назначен(а) исполнителем задачи. Свяжемся с тобой для дальнейших инструкций.",
                            )
                        # Store message for deletion after form submission
                        try:
                            await db.execute(
                                "UPDATE tasks SET assignment_chat_id = ?, assignment_message_id = ? WHERE task_id = ?",
                                (msg.chat.id, msg.message_id, task_row["task_id"]),
                            )
                        except Exception as store_err:
                            logger.warning("assignment_message_store_failed", task_id=task_row["task_id"], error=str(store_err))
                except Exception as e:
                    logger.warning("retry_user_notification_failed", task_nomber=task_nomber, error=str(e))
                    
        except PlanfixError as e:
            if e.is_task_not_found():
                # Task still not found, will retry later
                # This is normal - task nomber comes from webhook, but task may not be available via REST API yet
                logger.debug(
                    "retry_task_still_not_found",
                    task_nomber=task_nomber,
                    note="Task nomber from webhook, but task not yet available via REST API. Will retry."
                )
            else:
                # Other error, log it
                logger.warning("retry_executor_assignment_failed", task_nomber=task_nomber, error=str(e))
        except Exception as e:
            logger.error("retry_executor_assignment_error", task_nomber=task_nomber, error=str(e))


def shutdown_scheduler() -> None:
    """Shutdown the scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("scheduler_shutdown")
    else:
        logger.info("scheduler_already_stopped")








