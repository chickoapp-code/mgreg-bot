"""Application entry point."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import get_settings
from bot.database import get_database
from bot.handlers import invitations_router, registration_router
from bot.logging import configure_logging, get_logger
from bot.middleware import BotDataMiddleware
from bot.scheduler import shutdown_scheduler, start_scheduler
from bot.services.planfix import PlanfixClient
from bot.webhook_server import app as webhook_app, set_bot_instance


logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app):
    """Lifespan context manager for webhook server."""
    # Startup
    settings = get_settings()
    db = get_database(settings.database_path)
    await db.init()
    start_scheduler()
    yield
    # Shutdown
    shutdown_scheduler()


webhook_app.router.lifespan_context = lifespan


async def main() -> None:
    configure_logging()
    settings = get_settings()

    # Initialize database
    db = get_database(settings.database_path)
    await db.init()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    planfix_client = PlanfixClient(
        base_url=str(settings.planfix_base_url),
        token=settings.planfix_token,
        template_id=settings.planfix_template_id,
    )

    # Store data in dict (accessible in handlers via bot_data parameter through middleware)
    bot_data = {
        "admin_chat_id": settings.admin_chat_id,
        "admin_name": settings.admin_name,
        "planfix_base_url": str(settings.planfix_base_url),
        "planfix_client": planfix_client,
        "settings": settings,
    }

    # Set bot instance for webhook server
    set_bot_instance(bot)

    # Register middleware to inject bot_data into handlers
    bot_data_middleware = BotDataMiddleware(bot_data)
    registration_router.message.middleware(bot_data_middleware)
    registration_router.callback_query.middleware(bot_data_middleware)
    invitations_router.callback_query.middleware(bot_data_middleware)

    dp.include_router(registration_router)
    dp.include_router(invitations_router)

    async def on_startup_handler() -> None:
        logger.info("bot_startup")
        start_scheduler()

    async def on_shutdown_handler() -> None:
        logger.info("bot_shutdown")
        shutdown_scheduler()
        await planfix_client.close()

    dp.startup.register(on_startup_handler)
    dp.shutdown.register(on_shutdown_handler)

    # Start webhook server in background
    config = uvicorn.Config(
        webhook_app,
        host=settings.webhook_host,
        port=settings.webhook_port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    logger.info("bot_polling_start", webhook_port=settings.webhook_port)

    # Run bot and webhook server concurrently
    try:
        await asyncio.gather(
            dp.start_polling(bot),
            server.serve(),
        )
    finally:
        await planfix_client.close()


if __name__ == "__main__":
    asyncio.run(main())

