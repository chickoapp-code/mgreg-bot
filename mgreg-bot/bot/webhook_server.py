"""Webhook server for Planfix and Yandex Forms integration."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.config import get_settings
from bot.database import get_database
from bot.logging import get_logger
from bot.services.planfix import PlanfixClient, PlanfixError

logger = get_logger(__name__)
settings = get_settings()
app = FastAPI(title="Planfix-Telegram Bot Webhooks")

# Global instances (will be initialized in startup)
planfix_client: Optional[PlanfixClient] = None
bot_instance: Optional[Any] = None  # Telegram Bot instance


def verify_planfix_signature(body: bytes, signature: Optional[str]) -> bool:
    """Verify Planfix webhook signature."""
    if not settings.planfix_webhook_secret:
        return True  # Skip verification if secret not set
    if not signature:
        return False
    expected = hmac.new(
        settings.planfix_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


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


@app.on_event("startup")
async def startup() -> None:
    """Initialize services on startup."""
    global planfix_client
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
    """Cleanup on shutdown."""
    global planfix_client
    if planfix_client:
        await planfix_client.close()
    logger.info("webhook_server_shutdown")


@app.post("/webhooks/planfix")
async def planfix_webhook(
    request: Request,
    x_planfix_signature: Optional[str] = Header(None, alias="X-Planfix-Signature"),
) -> Dict[str, str]:
    """Handle webhook from Planfix."""
    body = await request.body()
    if not verify_planfix_signature(body, x_planfix_signature):
        logger.warning("planfix_webhook_invalid_signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = json.loads(body)
        event = data.get("event")
        task_id = data.get("taskId")

        if event == "task.created" and task_id:
            await handle_task_created(data)
        elif event == "task.updated" and task_id:
            await handle_task_updated(data)

        return {"status": "ok"}
    except Exception as e:
        logger.error("planfix_webhook_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def handle_task_created(data: Dict[str, Any]) -> None:
    """Handle task.created event."""
    task_id = data["taskId"]
    template = data.get("template", "")

    # Check if this is a restaurant check task
    if settings.task_template_ids_list:
        # Get full task details to check template ID
        try:
            task = await planfix_client.get_task(task_id, fields="id,template")
            template_obj = task.get("template", {})
            template_id = template_obj.get("id")
            if template_id not in settings.task_template_ids_list:
                logger.info("planfix_task_ignored", task_id=task_id, template_id=template_id)
                return
        except PlanfixError as e:
            logger.error("planfix_task_fetch_error", task_id=task_id, error=str(e))
            return

    # Extract task data
    restaurant = data.get("restaurant", {})
    restaurant_name = restaurant.get("name", "")
    restaurant_address = restaurant.get("address", "")
    visit_date = data.get("visitDate", "")
    deadline = data.get("deadline", "")
    invited_guests = data.get("invitedGuests", [])

    # Save task to database
    db = get_database()
    await db.execute(
        """
        INSERT OR REPLACE INTO tasks 
        (task_id, restaurant_name, restaurant_address, visit_date, deadline, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (task_id, restaurant_name, restaurant_address, visit_date, deadline, "pending", datetime.now().isoformat()),
    )

    # Check if executor already assigned
    task_details = await planfix_client.get_task(task_id, fields="id,assignees")
    assignees = task_details.get("assignees", [])
    if assignees:
        logger.info("planfix_task_already_assigned", task_id=task_id)
        return

    # Send invitations
    await send_invitations(task_id, invited_guests, restaurant_name, restaurant_address, visit_date)

    # Log in Planfix
    await planfix_client.add_task_comment(
        task_id,
        f"✅ Задача создана. Отправлено приглашений: {len(invited_guests)}",
    )


async def handle_task_updated(data: Dict[str, Any]) -> None:
    """Handle task.updated event."""
    # Can be used for additional logic if needed
    logger.info("planfix_task_updated", task_id=data.get("taskId"))


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
        task = await planfix_client.get_task(taskId, fields="id,name,description")
        task_name = task.get("name", f"Задача #{taskId}")
    except Exception:
        task_name = f"Задача #{taskId}"

    # Create redirect URL with session parameters
    redirect_url = f"{form_url}?sessionId={session_id}&taskId={taskId}&guestId={guestId}&form={form}"

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
        </style>
    </head>
    <body>
        <div class="card">
            <h2>{task_name}</h2>
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
        form = data.get("form")
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
                file_result = await planfix_client.upload_file_from_url(task_id, file_url)
                file_id = file_result.get("id") or file_result.get("file", {}).get("id")
                if file_id:
                    file_ids.append(file_id)
            except Exception as e:
                logger.error("file_upload_failed", url=file_url, error=str(e))

    if file_ids and settings.result_files_field_id:
        custom_field_data.append(
            {"field": {"id": settings.result_files_field_id}, "value": ",".join(map(str, file_ids))}
        )

    # Update task
    if custom_field_data:
        await planfix_client.update_task(task_id, custom_field_data=custom_field_data)

    # Change status to "Done"
    if settings.status_done_id:
        await planfix_client.update_task(task_id, status=settings.status_done_id)

    # Add comment
    comment_text = f"✅ Анкета получена от гостя (ID: {guest_id}). Форма: {form}."
    if score:
        comment_text += f" Оценка: {score}."
    await planfix_client.add_task_comment(task_id, comment_text)

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

