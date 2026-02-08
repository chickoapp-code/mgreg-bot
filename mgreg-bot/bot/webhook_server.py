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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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


def get_task_number_from_webhook(data: Dict[str, Any]) -> str | int | None:
    """Extract task number (nomber) from webhook data.
    
    Returns task number from 'nomber' field (can be in root or task.nomber), or falls back to taskId/task.id for backward compatibility.
    """
    # Try nomber in root first, then in task.nomber, then fallback to taskId/task.id
    return data.get("nomber") or data.get("task", {}).get("nomber") or data.get("taskId") or data.get("task", {}).get("id")


async def get_task_nomber_from_db(task_id: int | str) -> str | None:
    """Get nomber (task number) from database by task_id.
    
    Returns nomber if found, None otherwise.
    """
    db = get_database()
    task_row = await db.fetch_one(
        "SELECT nomber FROM tasks WHERE task_id = ?",
        (task_id,),
    )
    if task_row:
        try:
            nomber = task_row["nomber"]
            if nomber:
                return str(nomber)
        except (KeyError, TypeError):
            pass
    return None


async def get_task_nomber_for_api(task_id: int | str, webhook_data: Dict[str, Any] | None = None) -> str:
    """Get nomber (task number) for API calls.
    
    First tries to get from webhook data, then from database, then falls back to task_id.
    
    Args:
        task_id: Task ID from webhook or database
        webhook_data: Optional webhook data to extract nomber from
    
    Returns:
        Task nomber (number) to use for API calls
    """
    # Try webhook data first
    if webhook_data:
        nomber = webhook_data.get("nomber") or webhook_data.get("task", {}).get("nomber")
        if nomber:
            return str(nomber)
    
    # Try database
    nomber = await get_task_nomber_from_db(task_id)
    if nomber:
        return nomber
    
    # Fallback to task_id
    return str(task_id)


def verify_yforms_signature(body: bytes, signature: Optional[str]) -> bool:
    """Verify Yandex Forms webhook signature.
    
    If YFORMS_WEBHOOK_SECRET is not set, verification is skipped (returns True).
    This allows working with Yandex Forms which don't support HMAC signature calculation.
    """
    # Skip verification if secret is not configured
    if not settings.yforms_webhook_secret:
        return True
    
    # If secret is configured but signature is missing, fail
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


def _parse_yforms_result(result_raw: Any) -> Dict[str, Any]:
    """Parse result from Yandex Forms webhook. Handles number, string '100', or dict."""
    if isinstance(result_raw, (int, float)):
        return {"score": result_raw}
    if isinstance(result_raw, str):
        try:
            score_val = float(result_raw) if "." in result_raw else int(result_raw)
            return {"score": score_val}
        except (ValueError, TypeError):
            return {"score": None}
    if isinstance(result_raw, dict):
        return result_raw
    return {}


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
        try:
            data = json.loads(body)
        except json.JSONDecodeError as je:
            body_str = body.decode("utf-8", errors="replace")
            data = None
            # Planfix sometimes sends truncated JSON (missing root closing })
            fixed = body_str.rstrip()
            if fixed.endswith("}") and fixed.count("{") > fixed.count("}"):
                try:
                    data = json.loads(fixed + "}")
                    logger.info("planfix_webhook_json_fixed_truncated")
                except json.JSONDecodeError:
                    pass
            if data is None:
                try:
                    import json5
                    data = json5.loads(body_str)
                    logger.info("planfix_webhook_json5_fallback", json_error=str(je))
                except Exception:
                    logger.error("planfix_webhook_json_parse_failed", error=str(je), body_preview=body_str[:300])
                    raise
        logger.info("planfix_webhook_json_parsed", data_keys=list(data.keys()) if isinstance(data, dict) else None)
        
        event = data.get("event")
        # Use nomber (task number) from webhook instead of task_id
        task_number = get_task_number_from_webhook(data)

        logger.info("planfix_webhook_event_extracted", event_type=event, task_number=task_number)

        if not event or not task_number:
            # Avoid passing data dict directly to prevent event key conflict
            data_str = str(data) if data else "None"
            logger.warning("planfix_webhook_missing_fields", event_type=event, task_number=task_number, full_data_str=data_str)
            return {"status": "ok", "message": "Missing event or task number (nomber)"}

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
        elif event in ("task.updated", "task.update"):
            # Planfix sends task.update (or task.updated) on status change
            await handle_task_updated(data)
        elif event in ("task.status_answers_review", "task.status_payment_notification"):
            await handle_task_updated(data)
        else:
            logger.info("planfix_webhook_unknown_event", event_type=event, task_number=task_number)

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
    
    # Extract nomber (task number) from webhook - this is used for API calls
    # nomber is the actual task number (e.g., "86190"), not the task ID (e.g., "17859014")
    # nomber can be in root or in task.nomber
    task_nomber = get_task_number_from_webhook(data)
    if not task_nomber:
        # Avoid passing data dict directly to prevent event key conflict
        data_str = str(data) if data else "None"
        logger.error("planfix_task_created_missing_nomber", data_str=data_str)
        return
    
    logger.info(
        "planfix_task_created_processing",
        task_nomber=task_nomber,
        source="webhook",
        note="Task nomber (number) received from Planfix webhook. This will be used for API calls. Task may not be immediately available via REST API."
    )
    template = data.get("template", "") or data.get("task", {}).get("templateName", "")

    # Get full task details from Planfix using nomber (task number)
    try:
        task_details = await planfix_client.get_task(
            task_nomber,
            fields="id,name,description,template,dateTime,endDateTime,customFieldData",
        )
        
        # Check if this is a restaurant check task
        if settings.task_template_ids_list:
            template_obj = task_details.get("template", {})
            template_id = template_obj.get("id")
            logger.info("planfix_task_template_check", task_nomber=task_nomber, template_id=template_id, allowed_templates=settings.task_template_ids_list)
            if template_id not in settings.task_template_ids_list:
                logger.info("planfix_task_ignored", task_nomber=task_nomber, template_id=template_id, reason="template_not_in_allowed_list")
                return
        else:
            logger.info("planfix_task_template_check_skipped", task_nomber=task_nomber, reason="task_template_ids_list_not_configured")
        
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
        logger.info("extracting_guests_from_webhook", guests_count=len(guests_data) if isinstance(guests_data, list) else 0, guests_type=type(guests_data).__name__)
        if isinstance(guests_data, list):
            for g in guests_data:
                if isinstance(g, dict):
                    # Support both planfixContactId (from Planfix webhook) and id (backward compatibility)
                    guest_id = g.get("planfixContactId") or g.get("id") or g.get("planfix_contact_id")
                    guest_name = g.get("name", "Unknown")
                    logger.info("guest_dict_extracted", guest_id=guest_id, guest_name=guest_name)
                    if guest_id:
                        invited_guests.append(int(guest_id))
                elif isinstance(g, (int, str)):
                    # Direct ID (backward compatibility)
                    logger.info("guest_direct_id", guest_id=g)
                    invited_guests.append(int(g))
        logger.info("guests_extracted", invited_guests=invited_guests, count=len(invited_guests))
    except PlanfixError as e:
        logger.error("planfix_task_details_fetch_error", task_nomber=task_nomber, error=str(e))
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
        logger.info("extracting_guests_from_webhook_fallback", guests_count=len(guests_data) if isinstance(guests_data, list) else 0, guests_type=type(guests_data).__name__)
        if isinstance(guests_data, list):
            for g in guests_data:
                if isinstance(g, dict):
                    guest_id = g.get("planfixContactId") or g.get("id") or g.get("planfix_contact_id")
                    guest_name = g.get("name", "Unknown")
                    logger.info("guest_dict_extracted_fallback", guest_id=guest_id, guest_name=guest_name)
                    if guest_id:
                        invited_guests.append(int(guest_id))
                elif isinstance(g, (int, str)):
                    logger.info("guest_direct_id_fallback", guest_id=g)
                    invited_guests.append(int(g))
        logger.info("guests_extracted_fallback", invited_guests=invited_guests, count=len(invited_guests))

    # Save task to database
    # Extract both task_id (id) and nomber from webhook
    # task_id = id from webhook (e.g., "17859014") - stored in task_id column
    # nomber = nomber from webhook (e.g., "86190") - stored in nomber column, used for API calls
    task_id_from_webhook = data.get("taskId") or data.get("task", {}).get("id")
    
    # Convert to appropriate types for database
    try:
        task_id_db = int(task_id_from_webhook) if task_id_from_webhook else None
    except (ValueError, TypeError):
        task_id_db = task_id_from_webhook
    
    # nomber is stored as TEXT (already extracted above)
    nomber_db = str(task_nomber) if task_nomber else None
    
    db = get_database()
    # Normalize deadline for database storage
    normalized_deadline = normalize_planfix_date(deadline) if deadline else ""
    await db.execute(
        """
        INSERT OR REPLACE INTO tasks 
        (task_id, nomber, restaurant_name, restaurant_address, visit_date, deadline, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (task_id_db, nomber_db, restaurant_name, restaurant_address, visit_date, normalized_deadline, "pending", datetime.now().isoformat()),
    )

    # Check if executor already assigned using nomber (task number)
    try:
        task_assignees = await planfix_client.get_task(task_nomber, fields="id,assignees")
        assignees = task_assignees.get("assignees", {})
        # Handle both formats: object with "users" field or list
        if isinstance(assignees, dict):
            users = assignees.get("users", [])
        elif isinstance(assignees, list):
            users = assignees
        else:
            users = []
        if users:
            logger.info("planfix_task_already_assigned", task_nomber=task_nomber)
            return
    except PlanfixError as e:
        logger.error("planfix_task_assignees_check_failed", task_nomber=task_nomber, error=str(e))
        # Continue anyway - will check again when guest accepts

    # Extract budget (field 130) for invitation text
    reward_amount = None
    try:
        # Planfix API may return customFieldData, customfielddata, customfields, customFieldValues
        cf_data = (
            task_details.get("customFieldData")
            or task_details.get("customfielddata")
            or task_details.get("customfields")
            or task_details.get("customFieldValues")
            or task_details.get("customfieldvalues")
            or []
        )
        if settings.budget_field_id:
            # Support customFields as dict: {130: "1500"}
            cf_dict = task_details.get("customFields") or task_details.get("customfields") or {}
            if isinstance(cf_dict, dict):
                reward_amount = cf_dict.get(settings.budget_field_id) or cf_dict.get(str(settings.budget_field_id))
            # Support customFieldData as array
            if reward_amount is None:
                for item in cf_data:
                    if not isinstance(item, dict):
                        continue
                    # Support {field: {id: 130}, value: X}, {customField: {id: 130}, value: X}, {field: 130, value: X}, {id: 130, value: X}
                    field = item.get("field") or item.get("fieldId") or item.get("customField")
                    fid = field.get("id") if isinstance(field, dict) else (field if field is not None else item.get("id"))
                    if fid is not None and int(fid) == settings.budget_field_id:
                        reward_amount = item.get("value")
                        break
            # Fallback: try webhook payload (task object from Planfix)
            if reward_amount is None and data.get("task"):
                webhook_task = data.get("task", {}) if isinstance(data.get("task"), dict) else {}
                wf_cf = (
                    webhook_task.get("customFieldData")
                    or webhook_task.get("customfielddata")
                    or webhook_task.get("customFieldValues")
                    or []
                )
                for item in wf_cf:
                    if not isinstance(item, dict):
                        continue
                    field = item.get("field") or item.get("customField") or item.get("fieldId")
                    fid = field.get("id") if isinstance(field, dict) else (field if field is not None else item.get("id"))
                    if fid is not None and int(fid) == settings.budget_field_id:
                        reward_amount = item.get("value")
                        break
            logger.info("budget_extraction", task_nomber=task_nomber, reward_amount=reward_amount)
            if reward_amount is None and task_details:
                # Debug: log structure to diagnose Planfix API response format
                cf_raw = task_details.get("customFieldData") or task_details.get("customfielddata") or cf_data
                logger.info(
                    "budget_extraction_debug",
                    task_nomber=task_nomber,
                    task_keys=list(task_details.keys()),
                    cf_data_sample=str(cf_raw)[:500] if cf_raw else "empty",
                )
    except (NameError, TypeError, ValueError) as e:
        logger.warning("budget_extraction_failed", error=str(e))

    # Send invitations (using task_id for internal reference)
    await send_invitations(task_id_db, invited_guests, restaurant_name, restaurant_address, visit_date, reward_amount=reward_amount)

    # Set status to "В подборе гостя" (111)
    if settings.status_guest_selection_id:
        try:
            await planfix_client.update_task(task_nomber, status=settings.status_guest_selection_id)
        except PlanfixError as e:
            logger.error("planfix_status_guest_selection_failed", task_nomber=task_nomber, error=str(e))

    # Schedule deadline check
    if deadline:
        from bot.scheduler import schedule_deadline_check
        normalized_deadline = normalize_planfix_date(deadline)
        if normalized_deadline:
            await schedule_deadline_check(task_id_db, normalized_deadline, planfix_client)

    # Log in Planfix using nomber (task number)
    try:
        await planfix_client.add_task_comment(
            task_nomber,
            f"✅ Задача создана. Отправлено приглашений: {len(invited_guests)}",
        )
    except PlanfixError as e:
        logger.error("planfix_comment_add_failed", task_nomber=task_nomber, error=str(e))


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
    # Use nomber (task number) for API call
    try:
        task_nomber = await get_task_nomber_for_api(task_id, data)
        await planfix_client.add_task_comment(
            task_nomber,
            f"✅ Исполнитель назначен вручную: контакт ID {guest_id}",
        )
    except PlanfixError as e:
        logger.error("planfix_comment_add_failed", task_id=task_id, task_nomber=task_nomber if 'task_nomber' in locals() else None, error=str(e))


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
    # Use nomber (task number) for API call
    try:
        task_nomber = await get_task_nomber_for_api(task_id, data)
        await planfix_client.add_task_comment(
            task_nomber,
            f"⏳ Ожидаем заполнение анкеты. Дедлайн: {deadline or 'не указан'}",
        )
    except PlanfixError as e:
        logger.error("planfix_comment_add_failed", task_id=task_id, task_nomber=task_nomber if 'task_nomber' in locals() else None, error=str(e))


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
    Bot: updates DB, adds comment, notifies admin, sends guest success + payment amount.
    """
    task_id = data.get("taskId") or data.get("task", {}).get("id")
    guest = data.get("guest", {})
    # Support planfixContactId (from Planfix webhook) and id (backward compatibility)
    guest_id = None
    if isinstance(guest, dict):
        guest_id = guest.get("planfixContactId") or guest.get("id") or guest.get("planfix_contact_id")
    elif isinstance(guest, (int, str)):
        guest_id = int(guest)
    if guest_id is not None:
        guest_id = _parse_int(guest_id)
    
    result = data.get("result", {})
    finance = data.get("finance", {})
    
    logger.info("planfix_task_completed_compensation", task_id=task_id, guest_id=guest_id)
    
    # Notify guest: success message + payment amount
    db = get_database()
    if bot_instance and (guest_id or task_id):
        mapping = None
        if guest_id:
            mapping = await db.fetch_one(
                "SELECT telegram_id FROM guest_telegram_map WHERE planfix_contact_id = ?",
                (guest_id,),
            )
        # Planfix may send different guest ID than assigned_guest_id. Fallback to tasks.assigned_guest_id.
        if not mapping and task_id:
            task_id_int = _parse_int(task_id) if task_id else None
            if task_id_int is not None:
                task_row = await db.fetch_one(
                    "SELECT assigned_guest_id FROM tasks WHERE task_id = ?",
                    (task_id_int,),
                )
                if task_row and task_row["assigned_guest_id"]:
                    assigned_id = task_row["assigned_guest_id"]
                    if assigned_id != guest_id:
                        guest_id = assigned_id
                    mapping = await db.fetch_one(
                        "SELECT telegram_id FROM guest_telegram_map WHERE planfix_contact_id = ?",
                        (assigned_id,),
                    )
        # Fallback: try Planfix API assignees (e.g. contact:427) when tasks.assigned_guest_id is null.
        if not mapping and planfix_client:
            try:
                task_nomber = await get_task_nomber_for_api(task_id, data)
                task = await planfix_client.get_task(task_nomber, fields="assignees")
                assignees = task.get("assignees", {})
                users = assignees.get("users", []) if isinstance(assignees, dict) else (assignees if isinstance(assignees, list) else [])
                for u in users if users else []:
                    uid = (u.get("id") or u.get("userId")) if isinstance(u, dict) else None
                    if not uid:
                        continue
                    s = str(uid)
                    cid = int(s.split(":")[-1]) if ":" in s else _parse_int(s)
                    if cid:
                        mapping = await db.fetch_one(
                            "SELECT telegram_id FROM guest_telegram_map WHERE planfix_contact_id = ?",
                            (cid,),
                        )
                        if mapping:
                            guest_id = cid
                            break
            except (PlanfixError, Exception):
                pass
        if mapping:
            amount = None
            if isinstance(finance, dict):
                amount = finance.get("actual")  # Фактические расходы only
            amount_str = str(amount).strip() if amount is not None else "будет указана"
            msg = f"✅ Вы успешно прошли проверку.\n\nВам будет выплачена сумма: {amount_str}."
            try:
                await bot_instance.send_message(mapping["telegram_id"], msg)
                logger.info("guest_thank_you_completed_compensation_sent", guest_id=guest_id, amount=amount_str)
            except Exception as e:
                logger.error("guest_completed_compensation_notify_failed", guest_id=guest_id, error=str(e))
    
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
    
    # Use nomber (task number) for API call
    try:
        task_nomber = await get_task_nomber_for_api(task_id, data)
        await planfix_client.add_task_comment(task_nomber, comment_text)
    except PlanfixError as e:
        logger.error("planfix_comment_add_failed", task_id=task_id, task_nomber=task_nomber if 'task_nomber' in locals() else None, error=str(e))
    
    # Notify admin
    if bot_instance and settings.admin_chat_id:
        try:
            await bot_instance.send_message(
                settings.admin_chat_id,
                f"✅ Задача #{task_id} завершена, к компенсации. Гость: {guest_id}",
            )
        except Exception as e:
            logger.error("admin_completion_notification_failed", error=str(e))


def _extract_deadline_str(value: Any) -> str:
    """Extract deadline string from webhook payload.

    Planfix may send deadline as:
    - str: "15-02-2026"
    - dict: {"new": "15-02-2026"} or {"new": ""}
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("new", value.get("date", "")) or "")
    return ""


async def handle_task_deadline_updated(data: Dict[str, Any]) -> None:
    """Handle task.deadline_updated event - deadline changed.

    Note: Planfix automation has already updated deadline in Planfix.
    Bot should only update local database and reschedule deadline check.
    """
    task_id = data.get("taskId") or data.get("task", {}).get("id")
    # Support deadline from visit.deadline (Planfix format) or direct deadline
    visit = data.get("visit", {})
    raw_deadline = visit.get("deadline") if isinstance(visit, dict) else None
    if raw_deadline is None:
        raw_deadline = data.get("deadline") or data.get("task", {}).get("deadline", "")
    deadline = _extract_deadline_str(raw_deadline)

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


def _parse_int(v: Any) -> int | None:
    """Parse int from string or int."""
    if v is None:
        return None
    if isinstance(v, int):
        return v
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return None


async def handle_task_updated(data: Dict[str, Any]) -> None:
    """Handle task.updated / task.update event.

    When status is 116 (На проверке): send to guest "Ваша анкета на проверке".
    When status is 117: send to guest notification about payment amount from finance.budget/actual or field 132.
    Prefers webhook data (task.statusId, guest.planfixContactId, finance.budget/actual) over API fetch.
    """
    task_nomber = get_task_number_from_webhook(data)
    if not task_nomber:
        logger.warning("planfix_task_updated_missing_nomber")
        return

    if not planfix_client or not bot_instance:
        return

    task_obj = data.get("task") or {}
    guest_obj = data.get("guest") or {}
    finance_obj = data.get("finance") or {}
    api_task: Dict[str, Any] | None = None

    # Prefer statusId from webhook
    status_id = _parse_int(task_obj.get("statusId"))
    if status_id is None:
        try:
            api_task = await planfix_client.get_task(
                task_nomber,
                fields="id,status,assignees,customFieldData",
            )
        except PlanfixError as e:
            logger.warning("planfix_task_updated_fetch_failed", task_nomber=task_nomber, error=str(e))
            return
        status_obj = api_task.get("status")
        status_id = int(status_obj["id"]) if isinstance(status_obj, dict) and status_obj.get("id") else None

    if not status_id:
        return

    logger.info(
        "planfix_task_updated_processing",
        task_nomber=task_nomber,
        status_id=status_id,
        status_answers_review_id=settings.status_answers_review_id,
    )

    # Prefer guest from webhook (guest.planfixContactId)
    guest_planfix_id = _parse_int(guest_obj.get("planfixContactId"))
    if not guest_planfix_id:
        if not api_task:
            try:
                api_task = await planfix_client.get_task(task_nomber, fields="assignees")
            except PlanfixError:
                api_task = {}
        task = api_task or {}
        assignees = task.get("assignees", {})
        users = assignees.get("users", []) if isinstance(assignees, dict) else (assignees if isinstance(assignees, list) else [])
        if users:
            first_user = users[0] if users else {}
            user_id = first_user.get("id") if isinstance(first_user, dict) else None
            if user_id:
                s = str(user_id)
                if ":" in s:
                    guest_planfix_id = int(s.split(":")[-1])
                else:
                    guest_planfix_id = int(s)

    if not guest_planfix_id:
        db = get_database()
        task_id_from_webhook = task_obj.get("id") or data.get("taskId")
        task_id_int = _parse_int(task_id_from_webhook) if task_id_from_webhook else None
        task_row = await db.fetch_one(
            "SELECT assigned_guest_id FROM tasks WHERE nomber = ? OR task_id = ?",
            (str(task_nomber), task_id_int if task_id_int is not None else task_nomber),
        )
        if task_row:
            guest_planfix_id = task_row["assigned_guest_id"]

    if not guest_planfix_id:
        logger.info("planfix_task_updated_no_guest", task_nomber=task_nomber)
        return

    db = get_database()
    mapping = await db.fetch_one(
        "SELECT telegram_id FROM guest_telegram_map WHERE planfix_contact_id = ?",
        (guest_planfix_id,),
    )
    # Planfix may send different guest ID (e.g. 5189802) than assigned_guest_id (e.g. 427). Try assigned_guest_id from tasks.
    task_row = None
    if not mapping:
        task_id_from_webhook = task_obj.get("id") or data.get("taskId")
        task_id_int = _parse_int(task_id_from_webhook) if task_id_from_webhook else None
        task_row = await db.fetch_one(
            "SELECT assigned_guest_id FROM tasks WHERE nomber = ? OR task_id = ?",
            (str(task_nomber), task_id_int if task_id_int is not None else task_nomber),
        )
        if task_row and task_row["assigned_guest_id"]:
            assigned_id = task_row["assigned_guest_id"]
            mapping = await db.fetch_one(
                "SELECT telegram_id FROM guest_telegram_map WHERE planfix_contact_id = ?",
                (assigned_id,),
            )
            if mapping:
                logger.info("planfix_task_updated_guest_fallback", webhook_guest_id=guest_planfix_id, assigned_guest_id=assigned_id)
                guest_planfix_id = assigned_id

    # Fallback: assigned_guest_id in tasks is null. Try Planfix API assignees (e.g. contact:427).
    if not mapping and planfix_client:
        try:
            task = await planfix_client.get_task(task_nomber, fields="assignees")
            assignees = task.get("assignees", {})
            users = assignees.get("users", []) if isinstance(assignees, dict) else (assignees if isinstance(assignees, list) else [])
            for u in users if users else []:
                uid = (u.get("id") or u.get("userId")) if isinstance(u, dict) else None
                if not uid:
                    continue
                s = str(uid)
                cid = int(s.split(":")[-1]) if ":" in s else _parse_int(s)
                if cid:
                    mapping = await db.fetch_one(
                        "SELECT telegram_id FROM guest_telegram_map WHERE planfix_contact_id = ?",
                        (cid,),
                    )
                    if mapping:
                        logger.info("planfix_task_updated_guest_from_api", webhook_guest_id=guest_planfix_id, api_contact_id=cid)
                        guest_planfix_id = cid
                        break
        except PlanfixError as e:
            logger.warning("planfix_task_updated_api_fallback_failed", task_nomber=task_nomber, error=str(e))

    if not mapping:
        logger.warning(
            "planfix_task_updated_guest_not_in_bot",
            guest_id=guest_planfix_id,
            task_nomber=task_nomber,
            assigned_guest_id=task_row["assigned_guest_id"] if task_row else None,
        )
        return

    telegram_id = mapping["telegram_id"]

    if status_id == settings.status_answers_review_id:
        try:
            await bot_instance.send_message(telegram_id, "Ваша анкета на проверке.")
            logger.info("guest_notified_answers_review", task_nomber=task_nomber, guest_id=guest_planfix_id)
        except Exception as e:
            logger.error("guest_notify_answers_review_failed", telegram_id=telegram_id, error=str(e))

    elif status_id == settings.status_payment_notification_id:
        # Payment notification sent by task.completed_compensation only. Skip here to avoid duplicate.
        pass

    else:
        logger.info(
            "planfix_task_updated_status_no_notification",
            task_nomber=task_nomber,
            status_id=status_id,
            status_answers_review_id=settings.status_answers_review_id,
            status_payment_notification_id=settings.status_payment_notification_id,
        )


async def send_invitations(
    task_id: int,
    guest_ids: list[int],
    restaurant_name: str,
    restaurant_address: str,
    visit_date: str,
    *,
    reward_amount: str | int | float | None = None,
) -> None:
    """Send invitation messages to guests."""
    if not bot_instance:
        logger.error("bot_instance_not_available")
        return

    db = get_database()
    sent_count = 0
    not_found_guests = []

    logger.info("send_invitations_started", task_id=task_id, guest_ids=guest_ids, count=len(guest_ids))

    reward_line = ""
    if reward_amount is not None and str(reward_amount).strip():
        reward_line = f"Вознаграждение: {reward_amount}\n"

    for guest_id in guest_ids:
        # Get telegram_id from mapping
        mapping = await db.fetch_one(
            "SELECT telegram_id FROM guest_telegram_map WHERE planfix_contact_id = ?",
            (guest_id,),
        )
        if not mapping:
            logger.warning("guest_telegram_not_found", guest_id=guest_id, task_id=task_id)
            not_found_guests.append(guest_id)
            continue

        telegram_id = mapping["telegram_id"]

        # Send invitation message
        message_text = (
            f"Привет! Мы ищем Тайного гостя для ресторана «{restaurant_name}».\n"
            f"Адрес: {restaurant_address}\n"
            f"Проверка: {visit_date}\n"
            f"{reward_line}"
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
            logger.info("invitation_sent", task_id=task_id, guest_id=guest_id, telegram_id=telegram_id)
        except Exception as e:
            logger.error("invitation_send_failed", guest_id=guest_id, telegram_id=telegram_id, error=str(e))

    logger.info("invitations_sent", task_id=task_id, count=sent_count, total_guests=len(guest_ids), not_found_count=len(not_found_guests))
    
    # Notify admin if some guests were not found
    if not_found_guests and bot_instance and settings.admin_chat_id:
        try:
            guests_list = ", ".join(str(gid) for gid in not_found_guests)
            await bot_instance.send_message(
                settings.admin_chat_id,
                f"⚠️ Для задачи #{task_id} не найдены зарегистрированные гости в боте:\n"
                f"Planfix Contact IDs: {guests_list}\n"
                f"Эти гости должны зарегистрироваться в боте через /start",
            )
        except Exception as e:
            logger.error("admin_not_found_guests_notification_failed", error=str(e))


@app.get("/webhooks/planfix-guest/webapp/start")
@app.get("/webapp/start")  # Backward compatibility
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
    # Use nomber from database if available, otherwise use taskId
    try:
        task_nomber = await get_task_nomber_from_db(taskId)
        if not task_nomber:
            task_nomber = str(taskId)
        task = await planfix_client.get_task(task_nomber, fields="id,name,description,endDateTime")
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
):
    """Handle webhook from Yandex Forms."""
    body = await request.body()
    
    # Log signature for debugging
    body_preview = body[:200] if len(body) > 200 else body
    logger.info(
        "yforms_webhook_received",
        body_length=len(body),
        body_preview=body_preview.decode('utf-8', errors='ignore') if body_preview else None,
        signature_received=x_forms_signature[:20] + "..." if x_forms_signature and len(x_forms_signature) > 20 else x_forms_signature,
    )
    
    if not verify_yforms_signature(body, x_forms_signature):
        logger.warning(
            "yforms_webhook_invalid_signature",
            body_length=len(body),
            signature_received=x_forms_signature[:20] + "..." if x_forms_signature and len(x_forms_signature) > 20 else x_forms_signature,
            note="Check YFORMS_WEBHOOK_SECRET configuration"
        )
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = json.loads(body)
        
        # Handle JSON-RPC 2.0 format from Yandex Forms
        if data.get("jsonrpc") == "2.0":
            # Extract data from params
            params = data.get("params", {})
            session_id = params.get("sessionId")
            task_id = params.get("taskId")
            guest_id = params.get("guestId")
            # Support both old format (form) and new format (formCode)
            form = params.get("form") or params.get("formCode")
            result_raw = params.get("result", {})
            result = _parse_yforms_result(result_raw)
            attachments_raw = params.get("attachments", [])
            response_link = None
            if isinstance(attachments_raw, str) and attachments_raw.startswith("http"):
                response_link = attachments_raw
                attachments = []
            elif isinstance(attachments_raw, list):
                attachments = attachments_raw
            else:
                attachments = []
            response_link = response_link or params.get("responseUrl") or params.get("formResponseUrl")

            logger.info(
                "yforms_jsonrpc_received",
                method=data.get("method"),
                params_keys=list(params.keys()) if params else [],
                params_full=params,
                session_id=session_id,
                task_id=task_id,
                guest_id=guest_id,
                form=form,
            )
        else:
            # Handle direct format (legacy or alternative)
            session_id = data.get("sessionId")
            task_id = data.get("taskId")
            guest_id = data.get("guestId")
            # Support both old format (form) and new format (formCode)
            form = data.get("form") or data.get("formCode")
            result_raw = data.get("result", {})
            result = _parse_yforms_result(result_raw)
            attachments_raw = data.get("attachments", [])
            response_link = None
            if isinstance(attachments_raw, str) and attachments_raw.startswith("http"):
                response_link = attachments_raw
                attachments = []
            elif isinstance(attachments_raw, list):
                attachments = attachments_raw
            else:
                attachments = []
            response_link = response_link or data.get("responseUrl") or data.get("formResponseUrl")

        # Convert task_id to int if it's a string
        if task_id and isinstance(task_id, str):
            try:
                task_id = int(task_id)
            except (ValueError, TypeError):
                logger.warning("yforms_invalid_task_id", task_id=task_id, task_id_type=type(task_id).__name__)
        
        # Convert guest_id to int if it's a string
        if guest_id and isinstance(guest_id, str):
            try:
                guest_id = int(guest_id)
            except (ValueError, TypeError):
                logger.warning("yforms_invalid_guest_id", guest_id=guest_id, guest_id_type=type(guest_id).__name__)
        
        if not session_id or not task_id:
            logger.warning(
                "yforms_missing_fields",
                session_id=session_id,
                task_id=task_id,
                session_id_type=type(session_id).__name__ if session_id else None,
                task_id_type=type(task_id).__name__ if task_id else None,
                data_keys=list(data.keys()) if isinstance(data, dict) else [],
                params_keys=list(data.get("params", {}).keys()) if isinstance(data.get("params"), dict) else [],
                data_preview=str(data)[:500],
            )
            # Return JSON-RPC 2.0 error if request was JSON-RPC
            if isinstance(data, dict) and data.get("jsonrpc") == "2.0":
                response_id = data.get("id")
                if response_id is not None and not isinstance(response_id, str):
                    response_id = str(response_id)
                return JSONResponse(
                    status_code=200,  # JSON-RPC errors use 200 with error object
                    content={
                        "jsonrpc": "2.0",
                        "error": {"code": -32602, "message": "Missing required fields: sessionId and taskId"},
                        "id": response_id,
                    }
                )
            raise HTTPException(status_code=400, detail="Missing required fields: sessionId and taskId")

        await handle_form_submission(session_id, task_id, guest_id, form, result, attachments, response_link=response_link)

        # Return JSON-RPC 2.0 response if request was JSON-RPC
        if isinstance(data, dict) and data.get("jsonrpc") == "2.0":
            response_id = data.get("id")
            # Convert id to string if it's a number (JSON-RPC allows both, but FastAPI validation may expect string)
            if response_id is not None and not isinstance(response_id, str):
                response_id = str(response_id)
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "result": {"status": "ok"},
                "id": response_id,
            })
        return JSONResponse(content={"status": "ok"})
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error("yforms_webhook_json_decode_error", error=str(e), body_preview=body[:500].decode('utf-8', errors='ignore'))
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        logger.error("yforms_webhook_error", error=str(e), exc_info=True)
        # Try to return JSON-RPC 2.0 error if request was JSON-RPC
        try:
            parsed_data = json.loads(body)
            if isinstance(parsed_data, dict) and parsed_data.get("jsonrpc") == "2.0":
                response_id = parsed_data.get("id")
                if response_id is not None and not isinstance(response_id, str):
                    response_id = str(response_id)
                return JSONResponse(
                    status_code=200,  # JSON-RPC errors use 200 with error object
                    content={
                        "jsonrpc": "2.0",
                        "error": {"code": -32000, "message": str(e)},
                        "id": response_id,
                    }
                )
        except:
            pass
        raise HTTPException(status_code=500, detail=str(e))


async def handle_form_submission(
    session_id: str,
    task_id: int,
    guest_id: int,
    form: str,
    result: Dict[str, Any],
    attachments: list[Dict[str, Any]],
    *,
    response_link: Optional[str] = None,
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
    parts = []
    if response_link:
        parts.append(f"Ссылка на ответы: {response_link}")
    if score is not None:
        parts.append(f"Оценка: {score}")
    if summary:
        parts.append(summary)
    result_text = "\n".join(parts) if parts else ""
    if settings.result_field_id:
        # 136 - Результат прохождения
        custom_field_data.append({"field": {"id": settings.result_field_id}, "value": result_text})
    if settings.score_field_id and score:
        # 138 - Итоговый балл
        custom_field_data.append({"field": {"id": settings.score_field_id}, "value": str(score)})
    if settings.result_status_field_id:
        custom_field_data.append({"field": {"id": settings.result_status_field_id}, "value": "Завершено"})
    if settings.session_id_field_id:
        custom_field_data.append({"field": {"id": settings.session_id_field_id}, "value": session_id})
    # 144 - Последний статус синхронизации с ботом
    sync_status = f"Анкета получена {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    if settings.sync_status_field_id:
        custom_field_data.append({"field": {"id": settings.sync_status_field_id}, "value": sync_status})
    # 146 - Технический комментарий интеграции
    tech_comment = f"session_id={session_id}; form={form}; guest_id={guest_id}; score={score}; task_id={task_id}"
    if settings.integration_comment_field_id:
        custom_field_data.append({"field": {"id": settings.integration_comment_field_id}, "value": tech_comment})

    # Get nomber from database for API calls
    task_nomber = await get_task_nomber_from_db(task_id)
    if not task_nomber:
        task_nomber = str(task_id)
    
    # Upload files if any
    file_ids = []
    for attachment in attachments:
        file_url = attachment.get("url")
        if file_url:
            try:
                # Use nomber (task number) for API call
                file_result = await planfix_client.upload_file_from_url(task_nomber, file_url)
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

    # Update task (custom fields + status in one request for reliability)
    has_custom = bool(custom_field_data)
    status_id = settings.status_form_received_id or settings.status_done_id  # 115 Анкета получена
    has_status = status_id is not None
    if has_custom or has_status:
        try:
            await planfix_client.update_task(
                task_nomber,
                custom_field_data=custom_field_data if has_custom else None,
                status=status_id if has_status else None,
            )
        except PlanfixError as e:
            logger.error("planfix_task_update_failed", task_id=task_id, task_nomber=task_nomber, error=str(e))

    # Add comment
    comment_text = f"✅ Анкета получена от гостя (ID: {guest_id}). Форма: {form}."
    if score:
        comment_text += f" Оценка: {score}."
    # Use nomber (task number) for API call
    try:
        await planfix_client.add_task_comment(task_nomber, comment_text)
    except PlanfixError as e:
        logger.error("planfix_comment_add_failed", task_id=task_id, task_nomber=task_nomber, error=str(e))

    # Delete "Начать прохождение" message and send thank you to the guest
    if bot_instance:
        try:
            task_row = await db.fetch_one(
                "SELECT assignment_chat_id, assignment_message_id FROM tasks WHERE task_id = ?",
                (task_id,),
            )
            guest_mapping = await db.fetch_one(
                "SELECT telegram_id FROM guest_telegram_map WHERE planfix_contact_id = ?",
                (guest_id,),
            )
            # Delete the assignment message (sqlite3.Row uses indexing, not .get())
            chat_id = task_row["assignment_chat_id"] if task_row else None
            msg_id = task_row["assignment_message_id"] if task_row else None
            if chat_id is not None and msg_id is not None:
                try:
                    await bot_instance.delete_message(
                        chat_id=chat_id,
                        message_id=msg_id,
                    )
                except Exception as del_err:
                    logger.warning("assignment_message_delete_failed", task_id=task_id, error=str(del_err))
                await db.execute(
                    "UPDATE tasks SET assignment_chat_id = NULL, assignment_message_id = NULL WHERE task_id = ?",
                    (task_id,),
                )
            # Send thank you to the guest
            if guest_mapping:
                telegram_id = guest_mapping["telegram_id"]
                thank_you_text = (
                    "Благодарим за прохождение проверки! "
                    "Скоро вы получите вознаграждение."
                )
                await bot_instance.send_message(telegram_id, thank_you_text)
                logger.info("guest_thank_you_sent", task_id=task_id, guest_id=guest_id)
        except Exception as e:
            logger.error("guest_notification_failed", task_id=task_id, guest_id=guest_id, error=str(e))

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

