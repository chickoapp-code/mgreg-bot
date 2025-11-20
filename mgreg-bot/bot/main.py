"""Application entry point."""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import get_settings
from bot.handlers import registration_router
from bot.logging import configure_logging, get_logger
from bot.middleware import BotDataMiddleware
from bot.services.planfix import PlanfixClient


logger = get_logger(__name__)


async def main() -> None:
    configure_logging()
    settings = get_settings()

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
    }

    # Register middleware to inject bot_data into handlers
    bot_data_middleware = BotDataMiddleware(bot_data)
    registration_router.message.middleware(bot_data_middleware)
    registration_router.callback_query.middleware(bot_data_middleware)

    dp.include_router(registration_router)

    async def on_startup_handler() -> None:
        logger.info("bot_startup")

    async def on_shutdown_handler() -> None:
        logger.info("bot_shutdown")

    dp.startup.register(on_startup_handler)
    dp.shutdown.register(on_shutdown_handler)

    logger.info("bot_polling_start")
    try:
        await dp.start_polling(bot)
    finally:
        await planfix_client.close()


if __name__ == "__main__":
    asyncio.run(main())

