"""Управление конфигурацией приложения (загрузка переменных окружения)."""

from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings


load_dotenv()


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из переменных окружения."""

    bot_token: str = Field(alias="BOT_TOKEN")
    planfix_base_url: AnyHttpUrl = Field(alias="PLANFIX_BASE_URL")
    planfix_token: str = Field(alias="PLANFIX_TOKEN")
    admin_name: str = Field(alias="ADMIN_NAME")
    admin_chat_id: Optional[int] = Field(default=None, alias="ADMIN_CHAT_ID")
    planfix_template_id: int = Field(default=413, alias="PLANFIX_TEMPLATE_ID")

    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    """Вернуть кэшированный экземпляр настроек."""

    return Settings()

