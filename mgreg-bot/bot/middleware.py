"""Middleware for injecting bot data into handlers."""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class BotDataMiddleware(BaseMiddleware):
    """Middleware to inject bot_data into handler context."""

    def __init__(self, bot_data: Dict[str, Any]) -> None:
        super().__init__()
        self.bot_data = bot_data

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Inject bot_data into data dict
        data["bot_data"] = self.bot_data
        return await handler(event, data)

