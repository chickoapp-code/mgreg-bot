"""Webhook server for Planfix and Yandex Forms integration."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4


def normalize_planfix_date(date_str: str) -> str:
    """Convert Planfix date format (DD-MM-YYYY) to ISO format (YYYY-MM-DD)."""
    if not date_str:
        return ""
    
    # Try to parse DD-MM-YYYY format
    try:
        dt = datetime.strptime(date_str, "%d-%m-%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    
    # Try to parse DD.MM.YYYY format
    try:
        dt = datetime.strptime(date_str, "%d.%m.%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    
    # If already in ISO format or other format, try fromisoformat
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    
    # Return as-is if can't parse
    return date_str

from fastapi import FastAPI, Header, HTTPException, Request, Response, Security
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from bot.config import get_settings
from bot.database import get_database
from bot.logging import get_logger
from bot.services.planfix import PlanfixClient, PlanfixError

logger = get_logger(__name__)
settings = get_settings()
app = FastAPI(title="Planfix-Telegram Bot Webhooks")

# Middleware for request logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests."""
    start_time = datetime.now()
    logger.info(
        "http_request_received",
        method=request.method,
        path=request.url.path,
        query_params=str(request.query_params),
        client=request.client.host if request.client else None,
    )
    
    try:
        response = await call_next(request)
        process_time = (datetime.now() - start_time).total_seconds()
        logger.info(
            "http_request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            process_time=process_time,
        )
        return response
    except Exception as e:
        logger.error("http_request_error", method=request.method, path=request.url.path, error=str(e))
        raise

security = HTTPBasic()

# Global instances (will be initialized in startup)
planfix_client: Optional[PlanfixClient] = None
bot_instance: Optional[Any] = None  # Telegram Bot instance


def verify_planfix_basic_auth(credentials: HTTPBasicCredentials) -> bool:
    """Verify Planfix webhook Basic Auth credentials."""
    if not settings.planfix_webhook_login or not settings.planfix_webhook_password:
        return True  # Skip verification if credentials not set
    return (
        credentials.username == settings.planfix_webhook_login
        and credentials.password == settings.planfix_webhook_password
    )


def verify_yforms_signature(body: bytes, signature: Optional[str]) -> bool:
    """Verify Yandex Forms webhook signature."""
    if not signature:
        return False
    expected = hmac.new(
        settings.yforms_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def generate_webapp_signature(params: Dict[str, str], secret: str) -> str:
    """Generate HMAC signature for WebApp URL."""
    # Sort params and create query string
    sorted_params = sorted(params.items())
    query_string = "&".join(f"{k}={v}" for k, v in sorted_params)
    return hmac.new(
        secret.encode(),
        query_string.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_webapp_signature(params: Dict[str, str], signature: str, secret: str) -> bool:
    """Verify WebApp URL signature."""
    return hmac.compare_digest(generate_webapp_signature(params, secret), signature)


# Note: planfix_client is now initialized in main.py lifespan and set via set_planfix_client()
# Keeping @app.on_event handlers for backward compatibility, but they may not be called
# if lifespan context manager is used
@app.on_event("startup")
async def startup() -> None:
    """Initialize services on startup (fallback if lifespan is not used)."""
    global planfix_client
    if planfix_client is None:
        # Only initialize if not already set via set_planfix_client()
        db = get_database(settings.database_path)
        await db.init()
        planfix_client = PlanfixClient(
            base_url=str(settings.planfix_base_url),
            token=settings.planfix_token,
            template_id=settings.planfix_template_id,
        )
    logger.info("webhook_server_started")


@app.on_event("shutdown")
async def shutdown() -> None:
    """Cleanup on shutdown (fallback if lifespan is not used)."""
    # Note: planfix_client cleanup is handled in main.py lifespan
    logger.info("webhook_server_shutdown")


@app.get("/")
async def root() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "crmbot-webhook-server"}


@app.get("/health")
async def health() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "crmbot-webhook-server"}


@app.get("/webhooks/planfix-guest")
async def planfix_webhook_get() -> Dict[str, str]:
    """Health check for Planfix webhook endpoint."""
    return {
        "status": "ok",
        "message": "Planfix webhook endpoint is available. Use POST method to send webhooks.",
        "endpoint": "/webhooks/planfix-guest",
        "method": "POST",
    }


@app.post("/webhooks/planfix-guest")
async def planfix_webhook(
    request: Request,
    credentials: HTTPBasicCredentials = Security(security),
) -> Dict[str, str]:
    """Handle webhook from Planfix for guest invitation automation."""
    # Log incoming request
    logger.info("planfix_webhook_received", method=request.method, url=str(request.url), client=request.client.host if request.client else None)
    
    # Verify authentication
    if not verify_planfix_basic_auth(credentials):
        logger.warning("planfix_webhook_invalid_credentials", username=credentials.username)
        raise HTTPException(status_code=401, detail="Invalid credentials", headers={"WWW-Authenticate": "Basic"})
    
    logger.info("planfix_webhook_auth_success", username=credentials.username)
    
    body = await request.body()
    logger.info("planfix_webhook_body_received", body_length=len(body))

    try:
        data = json.loads(body)
        logger.info("planfix_webhook_json_parsed", data_keys=list(data.keys()) if isinstance(data, dict) else None)
        
        event = data.get("event")
        task_id = data.get("taskId") or data.get("task", {}).get("id")

        logger.info("planfix_webhook_event_extracted", event_type=event, task_id=task_id)

        if not event or not task_id:
            # Avoid passing data dict directly to prevent event key conflict
            data_str = str(data) if data else "None"
            logger.warning("planfix_webhook_missing_fields", event_type=event, task_id=task_id, full_data_str=data_str)
            return {"status": "ok", "message": "Missing event or taskId"}

        # Handle different event types according to TZ
        if event == "task.created":
            await handle_task_created(data)
        elif event == "task.assignee.manual":
            await handle_task_assignee_manual(data)
        elif event == "task.wait_form":
            await handle_task_wait_form(data)
        elif event == "task.deadline_failed":
            await handle_task_deadline_failed(data)
        elif event == "task.cancelled_manual":
            await handle_task_cancelled_manual(data)
        elif event == "task.completed_compensation":
            await handle_task_completed_compensation(data)
        elif event == "task.deadline_updated":
            await handle_task_deadline_updated(data)
        elif event == "task.updated":
            await handle_task_updated(data)
        else:
            logger.info("planfix_webhook_unknown_event", event_type=event, task_id=task_id)

        return {"status": "ok"}
    except Exception as e:
        logger.error("planfix_webhook_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def handle_task_created(data: Dict[str, Any]) -> None:
    """Handle task.created event.
    
    Note: Planfix automation has already changed status to "В подборе гостя".
    Bot should only send invitations and schedule deadline check.
    """
    logger.info("handle_task_created_started", data_keys=list(data.keys()) if isinstance(data, dict) else None)
    
    # Support both old format (taskId) and new format (task.id)
    task_id = data.get("taskId") or data.get("task", {}).get("id")
    if not task_id:
        # Avoid passing data dict directly to prevent event key conflict
        data_str = str(data) if data else "None"
        logger.error("planfix_task_created_missing_task_id", data_str=data_str)
        return
    
    logger.info("planfix_task_created_processing", task_id=task_id)
    template = data.get("template", "") or data.get("task", {}).get("templateName", "")

    # Get full task details from Planfix
    try:
        task_details = await planfix_client.get_task(
            int(task_id),
            fields="id,name,description,template,dateTime,endDateTime,customFieldData",
        )
        
        # Check if this is a restaurant check task
        if settings.task_template_ids_list:
            template_obj = task_details.get("template", {})
            template_id = template_obj.get("id")
            logger.info("planfix_task_template_check", task_id=task_id, template_id=template_id, allowed_templates=settings.task_template_ids_list)
            if template_id not in settings.task_template_ids_list:
                logger.info("planfix_task_ignored", task_id=task_id, template_id=template_id, reason="template_not_in_allowed_list")
                return
        else:
            logger.info("planfix_task_template_check_skipped", task_id=task_id, reason="task_template_ids_list_not_configured")
        
        # Extract data from task or webhook payload (webhook takes precedence for specific fields)
        # Support both old format (restaurant) and new format (task.restaurant)
        restaurant = data.get("restaurant", {}) or data.get("task", {}).get("restaurant", {})
        restaurant_name = restaurant.get("name") or task_details.get("name", "")
        restaurant_address = restaurant.get("address", "")
        
        # Support visit data from different locations
        visit = data.get("visit", {}) or data.get("task", {}).get("visit", {})
        visit_date = visit.get("date") or data.get("visitDate", "")
        
        # Support deadline from different locations (visit.deadline takes precedence)
        deadline = visit.get("deadline") or data.get("deadline") or data.get("task", {}).get("deadline", "")
        if not deadline and task_details.get("endDateTime"):
            end_dt = task_details.get("endDateTime", {})
            if isinstance(end_dt, dict):
                deadline = end_dt.get("date", "")
        
        # Extract guests from webhook payload
        # Planfix sends: guests: [{planfixContactId: "...", name: "..."}]
        invited_guests = []
        guests_data = data.get("guests", []) or data.get("invitedGuests", [])
        if isinstance(guests_data, list):
            for g in guests_data:
                if isinstance(g, dict):
                    # Support both planfixContactId (from Planfix webhook) and id (backward compatibility)
                    guest_id = g.get("planfixContactId") or g.get("id") or g.get("planfix_contact_id")
                    if guest_id:
                        invited_guests.append(int(guest_id))
                elif isinstance(g, (int, str)):
                    # Direct ID (backward compatibility)
                    invited_guests.append(int(g))
    except PlanfixError as e:
        logger.error("planfix_task_details_fetch_error", task_id=task_id, error=str(e))
        # Fallback to webhook data only
        restaurant = data.get("restaurant", {})
        restaurant_name = restaurant.get("name", "")
        restaurant_address = restaurant.get("address", "")
        visit = data.get("visit", {})
        visit_date = visit.get("date") or data.get("visitDate", "")
        deadline = visit.get("deadline") or data.get("deadline", "")
        
        # Extract guests from webhook payload (fallback)
        invited_guests = []
        guests_data = data.get("guests", []) or data.get("invitedGuests", [])
        if isinstance(guests_data, list):
            for g in guests_data:
                if isinstance(g, dict):
                    guest_id = g.get("planfixContactId") or g.get("id") or g.get("planfix_contact_id")
                    if guest_id:
                        invited_guests.append(int(guest_id))
                elif isinstance(g, (int, str)):
                    invited_guests.append(int(g))

    # Save task to database
    db = get_database()
    # Normalize deadline for database storage
    normalized_deadline = normalize_planfix_date(deadline) if deadline else ""
    await db.execute(
        """
        INSERT OR REPLACE INTO tasks 
        (task_id, restaurant_name, restaurant_address, visit_date, deadline, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (task_id, restaurant_name, restaurant_address, visit_date, normalized_deadline, "pending", datetime.now().isoformat()),
    )

    # Check if executor already assigned
    try:
        task_assignees = await planfix_client.get_task(int(task_id), fields="id,assignees")
        assignees = task_assignees.get("assignees", [])
        if assignees:
            logger.info("planfix_task_already_assigned", task_id=task_id)
            return
    except PlanfixError as e:
        logger.error("planfix_task_assignees_check_failed", task_id=task_id, error=str(e))
        # Continue anyway - will check again when guest accepts

    # Send invitations
    await send_invitations(task_id, invited_guests, restaurant_name, restaurant_address, visit_date)

    # Schedule deadline check
    if deadline:
        from bot.scheduler import schedule_deadline_check
        normalized_deadline = normalize_planfix_date(deadline)
        if normalized_deadline:
            await schedule_deadline_check(int(task_id), normalized_deadline, planfix_client)

    # Log in Planfix
    try:
        await planfix_client.add_task_comment(
            int(task_id),
            f"✅ Задача создана. Отправлено приглашений: {len(invited_guests)}",
        )
    except PlanfixError as e:
        logger.error("planfix_comment_add_failed", task_id=task_id, error=str(e))


async def handle_task_assignee_manual(data: Dict[str, Any]) -> None:
    """Handle task.assignee.manual event - manual executor assignment.
    
    Note: Planfix automation has already changed status to "Гость назначен".
    Bot should only update local database.
    """
    task_id = data.get("taskId") or data.get("task", {}).get("id")
    guest = data.get("guest", {})
    # Support planfixContactId (from Planfix webhook) and id (backward compatibility)
    guest_id = None
    if isinstance(guest, dict):
        guest_id = guest.get("planfixContactId") or guest.get("id") or guest.get("planfix_contact_id")
    elif isinstance(guest, (int, str)):
        guest_id = int(guest)
    
    logger.info("planfix_task_assignee_manual", task_id=task_id, guest_id=guest_id)
    
    # Update database
    # Note: Planfix automation has already changed status to "Гость назначен"
    db = get_database()
    await db.execute(
        """
        UPDATE tasks 
        SET assigned_guest_id = ?, status = 'assigned'
        WHERE task_id = ?
        """,
        (guest_id, task_id),
    )
    
    # Optional: Add informational comment (automation may not add comment)
    try:
        await planfix_client.add_task_comment(
            int(task_id),
            f"✅ Исполнитель назначен вручную: контакт ID {guest_id}",
        )
    except PlanfixError as e:
        logger.error("planfix_comment_add_failed", task_id=task_id, error=str(e))


async def handle_task_wait_form(data: Dict[str, Any]) -> None:
    """Handle task.wait_form event - task waiting for form submission.
    
    Note: Planfix automation has already changed status to "Ожидаем анкету" and set deadline.
    Bot should only update local database and reschedule deadline check.
    """
    task_id = data.get("taskId") or data.get("task", {}).get("id")
    guest = data.get("guest", {})
    # Support planfixContactId (from Planfix webhook) and id (backward compatibility)
    guest_id = None
    if isinstance(guest, dict):
        guest_id = guest.get("planfixContactId") or guest.get("id") or guest.get("planfix_contact_id")
    elif isinstance(guest, (int, str)):
        guest_id = int(guest)
    
    # Support deadline from visit.deadline (Planfix format) or direct deadline
    visit = data.get("visit", {})
    deadline = visit.get("deadline") if isinstance(visit, dict) else None
    if not deadline:
        deadline = data.get("deadline") or data.get("task", {}).get("deadline", "")
    
    logger.info("planfix_task_wait_form", task_id=task_id, guest_id=guest_id, deadline=deadline)
    
    # Update database
    # Note: Planfix automation has already changed status to "Ожидаем анкету" and set deadline if needed
    db = get_database()
    normalized_deadline = normalize_planfix_date(deadline) if deadline else ""
    await db.execute(
        """
        UPDATE tasks 
        SET status = 'waiting_form', deadline = ?
        WHERE task_id = ?
        """,
        (normalized_deadline, task_id),
    )
    
    # Schedule deadline check if not already scheduled
    if deadline:
        from bot.scheduler import schedule_deadline_check
        normalized_deadline = normalize_planfix_date(deadline)
        if normalized_deadline:
            await schedule_deadline_check(int(task_id), normalized_deadline, planfix_client)
    
    # Optional: Add informational comment (automation may not add comment)
    try:
        await planfix_client.add_task_comment(
            int(task_id),
            f"⏳ Ожидаем заполнение анкеты. Дедлайн: {deadline or 'не указан'}",
        )
    except PlanfixError as e:
        logger.error("planfix_comment_add_failed", task_id=task_id, error=str(e))


async def handle_task_deadline_failed(data: Dict[str, Any]) -> None:
    """Handle task.deadline_failed event - deadline expired without submission.
    
    Note: Planfix automation has already changed status to "Отменена по дедлайну" and added comment.
    Bot should only update local database and notify admin.
    """
    task_id = data.get("taskId") or data.get("task", {}).get("id")
    guest = data.get("guest", {})
    # Support planfixContactId (from Planfix webhook) and id (backward compatibility)
    guest_id = None
    if isinstance(guest, dict):
        guest_id = guest.get("planfixContactId") or guest.get("id") or guest.get("planfix_contact_id")
    elif isinstance(guest, (int, str)):
        guest_id = int(guest)
    
    reason = data.get("reason", "Анкета не получена до дедлайна")
    
    logger.info("planfix_task_deadline_failed", task_id=task_id, guest_id=guest_id)
    
    # Update database
    # Note: Planfix automation has already changed status to "Отменена по дедлайну" and added comment
    db = get_database()
    await db.execute(
        """
        UPDATE tasks 
        SET status = 'cancelled_deadline'
        WHERE task_id = ?
        """,
        (task_id,),
    )
    
    # Note: Status and comment are already set by Planfix automation
    # Bot only updates local database and notifies admin
    
    # Notify admin
    if bot_instance and settings.admin_chat_id:
        try:
            await bot_instance.send_message(
                settings.admin_chat_id,
                f"⏰ Дедлайн истёк для задачи #{task_id}. Проверка не была пройдена. Задача отменена.",
            )
        except Exception as e:
            logger.error("admin_deadline_notification_failed", error=str(e))


async def handle_task_cancelled_manual(data: Dict[str, Any]) -> None:
    """Handle task.cancelled_manual event - manual cancellation.
    
    Note: Planfix automation has already changed status to "Отменена вручную".
    Optional comment with reason may be added by automation if "Причина отмены" field is used.
    Bot should only update local database and notify admin.
    """
    task_id = data.get("taskId") or data.get("task", {}).get("id")
    guest = data.get("guest", {})
    # Support planfixContactId (from Planfix webhook) and id (backward compatibility)
    guest_id = None
    if isinstance(guest, dict):
        guest_id = guest.get("planfixContactId") or guest.get("id") or guest.get("planfix_contact_id")
    elif isinstance(guest, (int, str)):
        guest_id = int(guest)
    
    cancel = data.get("cancel", {})
    reason = cancel.get("reason") if isinstance(cancel, dict) else (cancel if isinstance(cancel, str) else None)
    
    logger.info("planfix_task_cancelled_manual", task_id=task_id, guest_id=guest_id, reason=reason)
    
    # Update database
    # Note: Planfix automation has already changed status to "Отменена вручную"
    # Optional comment with reason may be added by automation if "Причина отмены" field is used
    db = get_database()
    await db.execute(
        """
        UPDATE tasks 
        SET status = 'cancelled_manual'
        WHERE task_id = ?
        """,
        (task_id,),
    )
    
    # Note: Status is already changed by Planfix automation
    # Comment with reason may already be added by automation
    # Bot only updates local database and notifies admin
    
    # Notify admin
    if bot_instance and settings.admin_chat_id:
        try:
            await bot_instance.send_message(
                settings.admin_chat_id,
                f"❌ Задача #{task_id} отменена вручную. Причина: {reason or 'не указана'}",
            )
        except Exception as e:
            logger.error("admin_cancellation_notification_failed", error=str(e))


async def handle_task_completed_compensation(data: Dict[str, Any]) -> None:
    """Handle task.completed_compensation event - task completed, ready for compensation.
    
    Note: Planfix automation has already changed status to "Завершена (к компенсации)".
    Bot should only update local database, add comment with results, and notify admin.
    """
    task_id = data.get("taskId") or data.get("task", {}).get("id")
    guest = data.get("guest", {})
    # Support planfixContactId (from Planfix webhook) and id (backward compatibility)
    guest_id = None
    if isinstance(guest, dict):
        guest_id = guest.get("planfixContactId") or guest.get("id") or guest.get("planfix_contact_id")
    elif isinstance(guest, (int, str)):
        guest_id = int(guest)
    
    result = data.get("result", {})
    finance = data.get("finance", {})
    
    logger.info("planfix_task_completed_compensation", task_id=task_id, guest_id=guest_id)
    
    # Update database
    # Note: Planfix automation has already changed status to "Завершена (к компенсации)"
    db = get_database()
    await db.execute(
        """
        UPDATE tasks 
        SET status = 'completed_compensation'
        WHERE task_id = ?
        """,
        (task_id,),
    )
    
    # Add comment with results (optional - automation may not add detailed comment)
    comment_text = f"✅ Задача завершена, к компенсации."
    if isinstance(result, dict):
        score = result.get("score")
        summary = result.get("summary")
        if score:
            comment_text += f" Оценка: {score}."
        if summary:
            comment_text += f" {summary}"
    if isinstance(finance, dict):
        budget = finance.get("budget")
        actual = finance.get("actual")
        status = finance.get("status")
        if budget or actual:
            comment_text += f" Бюджет: {budget or 'не указан'}, Факт: {actual or 'не указан'}."
        if status:
            comment_text += f" Статус возмещения: {status}."
    
    try:
        await planfix_client.add_task_comment(int(task_id), comment_text)
    except PlanfixError as e:
        logger.error("planfix_comment_add_failed", task_id=task_id, error=str(e))
    
    # Notify admin
    if bot_instance and settings.admin_chat_id:
        try:
            await bot_instance.send_message(
                settings.admin_chat_id,
                f"✅ Задача #{task_id} завершена, к компенсации. Гость: {guest_id}",
            )
        except Exception as e:
            logger.error("admin_completion_notification_failed", error=str(e))


async def handle_task_deadline_updated(data: Dict[str, Any]) -> None:
    """Handle task.deadline_updated event - deadline changed.
    
    Note: Planfix automation has already updated deadline in Planfix.
    Bot should only update local database and reschedule deadline check.
    """
    task_id = data.get("taskId") or data.get("task", {}).get("id")
    # Support deadline from visit.deadline (Planfix format) or direct deadline
    visit = data.get("visit", {})
    deadline = visit.get("deadline") if isinstance(visit, dict) else None
    if not deadline:
        deadline = data.get("deadline") or data.get("task", {}).get("deadline", "")
    
    logger.info("planfix_task_deadline_updated", task_id=task_id, deadline=deadline)
    
    # Update database
    # Note: Planfix automation has already updated deadline in Planfix
    db = get_database()
    normalized_deadline = normalize_planfix_date(deadline) if deadline else ""
    await db.execute(
        """
        UPDATE tasks 
        SET deadline = ?
        WHERE task_id = ?
        """,
        (normalized_deadline, task_id),
    )
    
    # Reschedule deadline check
    if deadline:
        from bot.scheduler import schedule_deadline_check
        normalized_deadline = normalize_planfix_date(deadline)
        if normalized_deadline:
            await schedule_deadline_check(int(task_id), normalized_deadline, planfix_client)
    
    # Note: Deadline is already updated in Planfix by automation
    # Bot only updates local database and reschedules deadline check


async def handle_task_updated(data: Dict[str, Any]) -> None:
    """Handle task.updated event."""
    # Can be used for additional logic if needed
    task_id = data.get("taskId") or data.get("task", {}).get("id")
    logger.info("planfix_task_updated", task_id=task_id)


async def send_invitations(
    task_id: int,
    guest_ids: list[int],
    restaurant_name: str,
    restaurant_address: str,
    visit_date: str,
) -> None:
    """Send invitation messages to guests."""
    if not bot_instance:
        logger.error("bot_instance_not_available")
        return

    db = get_database()
    sent_count = 0

    for guest_id in guest_ids:
        # Get telegram_id from mapping
        mapping = await db.fetch_one(
            "SELECT telegram_id FROM guest_telegram_map WHERE planfix_contact_id = ?",
            (guest_id,),
        )
        if not mapping:
            logger.warning("guest_telegram_not_found", guest_id=guest_id)
            continue

        telegram_id = mapping["telegram_id"]

        # Send invitation message
        message_text = (
            f"Привет! Мы ищем Тайного гостя для ресторана «{restaurant_name}».\n"
            f"Адрес: {restaurant_address}\n"
            f"Проверка: {visit_date}\n"
            f"Нажми «Принять», если готов(а) пройти проверку."
        )

        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Принять", callback_data=f"accept|{task_id}"),
                    InlineKeyboardButton(text="Отказаться", callback_data=f"decline|{task_id}"),
                ]
            ]
        )

        try:
            message = await bot_instance.send_message(telegram_id, message_text, reply_markup=keyboard)
            # Save invitation
            await db.execute(
                """
                INSERT INTO invitations 
                (task_id, guest_planfix_id, telegram_id, chat_id, message_id, sent_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, guest_id, telegram_id, message.chat.id, message.message_id, datetime.now().isoformat()),
            )
            sent_count += 1
        except Exception as e:
            logger.error("invitation_send_failed", guest_id=guest_id, error=str(e))

    logger.info("invitations_sent", task_id=task_id, count=sent_count)


@app.get("/webapp/start")
async def webapp_start(
    taskId: int,
    guestId: int,
    form: str,
    sig: str,
    ts: Optional[str] = None,
) -> HTMLResponse:
    """WebApp start page with form redirect."""
    # Verify signature
    params = {"taskId": str(taskId), "guestId": str(guestId), "form": form}
    if ts:
        params["ts"] = ts
    if not verify_webapp_signature(params, sig, settings.webapp_hmac_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Generate session ID
    session_id = str(uuid4())

    # Save session
    db = get_database()
    await db.execute(
        """
        INSERT INTO form_sessions (session_id, task_id, guest_planfix_id, form, started_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, taskId, guestId, form, datetime.now().isoformat()),
    )

    # Get form URL
    form_urls = settings.form_urls_dict
    form_url = form_urls.get(form)
    if not form_url:
        raise HTTPException(status_code=404, detail=f"Form {form} not found")

    # Get task details for display
    try:
        task = await planfix_client.get_task(taskId, fields="id,name,description,endDateTime")
        task_name = task.get("name", f"Задача #{taskId}")
        # Extract deadline for display
        end_dt = task.get("endDateTime", {})
        deadline_display = ""
        if isinstance(end_dt, dict):
            deadline_date = end_dt.get("date", "")
            deadline_time = end_dt.get("time", "")
            if deadline_date:
                deadline_display = f"Дедлайн: {deadline_date}"
                if deadline_time:
                    deadline_display += f" {deadline_time}"
    except Exception:
        task_name = f"Задача #{taskId}"
        deadline_display = ""

    # Create redirect URL with session parameters (according to TZ: formCode and sessionId)
    # Support both old format (form) and new format (formCode)
    form_code = form  # Use form as formCode if not specified separately
    redirect_url = f"{form_url}?taskId={taskId}&guestId={guestId}&formCode={form_code}&sessionId={session_id}"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Проверка ресторана</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                padding: 20px;
                max-width: 600px;
                margin: 0 auto;
            }}
            .card {{
                background: #f5f5f5;
                border-radius: 12px;
                padding: 20px;
                margin-bottom: 20px;
            }}
            .button {{
                display: block;
                width: 100%;
                padding: 15px;
                background: #0088cc;
                color: white;
                text-align: center;
                border-radius: 8px;
                text-decoration: none;
                font-weight: bold;
                margin-top: 15px;
            }}
            .deadline {{
                color: #666;
                font-size: 14px;
                margin-top: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2>{task_name}</h2>
            {f'<p class="deadline">{deadline_display}</p>' if deadline_display else ''}
            <p>Нажмите кнопку ниже, чтобы открыть форму для заполнения.</p>
            <a href="{redirect_url}" class="button">Открыть форму</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.post("/webhooks/yforms")
async def yforms_webhook(
    request: Request,
    x_forms_signature: Optional[str] = Header(None, alias="X-Forms-Signature"),
) -> Dict[str, str]:
    """Handle webhook from Yandex Forms."""
    body = await request.body()
    if not verify_yforms_signature(body, x_forms_signature):
        logger.warning("yforms_webhook_invalid_signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = json.loads(body)
        session_id = data.get("sessionId")
        task_id = data.get("taskId")
        guest_id = data.get("guestId")
        # Support both old format (form) and new format (formCode)
        form = data.get("form") or data.get("formCode")
        result = data.get("result", {})
        attachments = data.get("attachments", [])

        if not session_id or not task_id:
            raise HTTPException(status_code=400, detail="Missing required fields")

        await handle_form_submission(session_id, task_id, guest_id, form, result, attachments)

        return {"status": "ok"}
    except Exception as e:
        logger.error("yforms_webhook_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def handle_form_submission(
    session_id: str,
    task_id: int,
    guest_id: int,
    form: str,
    result: Dict[str, Any],
    attachments: list[Dict[str, Any]],
) -> None:
    """Handle form submission."""
    db = get_database()

    # Check if already processed (idempotency)
    existing = await db.fetch_one(
        "SELECT completed_at FROM form_sessions WHERE session_id = ?",
        (session_id,),
    )
    if existing and existing["completed_at"]:
        logger.info("form_submission_already_processed", session_id=session_id)
        return

    score = result.get("score")
    summary = result.get("summary", "")
    payload_json = json.dumps(result.get("raw", {}))

    # Update session
    await db.execute(
        """
        UPDATE form_sessions 
        SET completed_at = ?, score = ?, summary = ?, payload = ?
        WHERE session_id = ?
        """,
        (datetime.now().isoformat(), score, summary, payload_json, session_id),
    )

    # Update Planfix task
    custom_field_data = []
    if settings.result_field_id:
        result_text = f"Оценка: {score}\n{summary}" if score else summary
        custom_field_data.append({"field": {"id": settings.result_field_id}, "value": result_text})

    # Upload files if any
    file_ids = []
    for attachment in attachments:
        file_url = attachment.get("url")
        if file_url:
            try:
                file_result = await planfix_client.upload_file_from_url(int(task_id), file_url)
                file_id = file_result.get("id") or file_result.get("file", {}).get("id")
                if file_id:
                    file_ids.append(file_id)
            except Exception as e:
                logger.error("file_upload_failed", url=file_url, error=str(e))

    if file_ids and settings.result_files_field_id:
        # Planfix expects file IDs as array for file custom fields
        custom_field_data.append(
            {"field": {"id": settings.result_files_field_id}, "value": file_ids}
        )

    # Update task
    if custom_field_data:
        try:
            await planfix_client.update_task(int(task_id), custom_field_data=custom_field_data)
        except PlanfixError as e:
            logger.error("planfix_task_update_failed", task_id=task_id, error=str(e))

    # Change status to "Done"
    if settings.status_done_id:
        try:
            await planfix_client.update_task(int(task_id), status=settings.status_done_id)
        except PlanfixError as e:
            logger.error("planfix_status_update_failed", task_id=task_id, error=str(e))

    # Add comment
    comment_text = f"✅ Анкета получена от гостя (ID: {guest_id}). Форма: {form}."
    if score:
        comment_text += f" Оценка: {score}."
    try:
        await planfix_client.add_task_comment(int(task_id), comment_text)
    except PlanfixError as e:
        logger.error("planfix_comment_add_failed", task_id=task_id, error=str(e))

    # Notify admin
    if bot_instance and settings.admin_chat_id:
        try:
            admin_message = (
                f"✅ Проверка завершена!\n"
                f"Задача: #{task_id}\n"
                f"Гость: {guest_id}\n"
                f"Форма: {form}\n"
                f"Оценка: {score}" if score else "Оценка не указана"
            )
            await bot_instance.send_message(settings.admin_chat_id, admin_message)
        except Exception as e:
            logger.error("admin_notification_failed", error=str(e))

    logger.info("form_submission_processed", session_id=session_id, task_id=task_id)


def set_bot_instance(bot: Any) -> None:
    """Set Telegram bot instance for sending messages."""
    global bot_instance
    bot_instance = bot


def set_planfix_client(client: PlanfixClient) -> None:
    """Set Planfix client instance for webhook handlers."""
    global planfix_client
    planfix_client = client

