"""Scheduler for deadline jobs."""

from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from bot.config import get_settings
from bot.database import get_database
from bot.logging import get_logger
from bot.services.planfix import PlanfixClient, PlanfixError

logger = get_logger(__name__)
settings = get_settings()
scheduler = AsyncIOScheduler()


async def check_task_deadline(task_id: int, client: PlanfixClient) -> None:
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
            await client.update_task(task_id, status=settings.status_cancelled_id)
            await client.add_task_comment(
                task_id,
                "⏰ Дедлайн истёк. Проверка не была пройдена. Задача отменена.",
            )
            logger.info("task_deadline_cancelled", task_id=task_id)

            # Notify admin
            admin_chat_id = settings.admin_chat_id
            if admin_chat_id:
                # Note: Requires bot instance, handled in main.py
                pass

    except PlanfixError as e:
        logger.error("task_deadline_check_failed", task_id=task_id, error=str(e))


async def schedule_deadline_check(task_id: int, deadline_str: str, client: PlanfixClient) -> None:
    """Schedule deadline check for task."""
    try:
        # Parse deadline
        deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
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
    scheduler.start()
    logger.info("scheduler_started")


def shutdown_scheduler() -> None:
    """Shutdown the scheduler."""
    scheduler.shutdown()
    logger.info("scheduler_shutdown")




