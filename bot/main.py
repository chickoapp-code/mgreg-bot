"""Точка входа приложения Telegram-бота."""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher

from bot.config import get_settings
from bot.handlers import registration_router
from bot.logging import configure_logging, get_logger
from bot.services.planfix import PlanfixClient


logger = get_logger(__name__)


async def on_startup(bot: Bot, client: PlanfixClient) -> None:
    """Действия при старте: привязать клиент Planfix к экземпляру бота."""
    logger.info("bot_startup")
    bot["planfix_client"] = client


async def on_shutdown(bot: Bot, client: PlanfixClient) -> None:
    """Корректное завершение: закрыть HTTP-клиент Planfix."""
    logger.info("bot_shutdown")
    await client.close()


async def main() -> None:
    configure_logging()
    settings = get_settings()

    bot = Bot(token=settings.bot_token, parse_mode="HTML")
    dp = Dispatcher()

    planfix_client = PlanfixClient(
        base_url=str(settings.planfix_base_url),
        token=settings.planfix_token,
        template_id=settings.planfix_template_id,
    )

    bot["admin_chat_id"] = settings.admin_chat_id
    bot["admin_name"] = settings.admin_name
    bot["planfix_base_url"] = str(settings.planfix_base_url)

    dp.include_router(registration_router)

    dp.startup.register(lambda bot_: on_startup(bot_, planfix_client))
    dp.shutdown.register(lambda bot_: on_shutdown(bot_, planfix_client))

    logger.info("bot_polling_start")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

