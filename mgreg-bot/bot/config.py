"""Application configuration management."""

from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings


load_dotenv()


class Settings(BaseSettings):
    """Configuration values loaded from environment variables."""

    bot_token: str = Field(alias="BOT_TOKEN")
    planfix_base_url: AnyHttpUrl = Field(alias="PLANFIX_BASE_URL")
    planfix_token: str = Field(alias="PLANFIX_TOKEN")
    admin_name: str = Field(alias="ADMIN_NAME")
    admin_chat_id: Optional[int] = Field(default=None, alias="ADMIN_CHAT_ID")
    planfix_template_id: int = Field(default=413, alias="PLANFIX_TEMPLATE_ID")

    # Webhook authentication
    planfix_webhook_login: Optional[str] = Field(default=None, alias="PLANFIX_WEBHOOK_LOGIN")
    planfix_webhook_password: Optional[str] = Field(default=None, alias="PLANFIX_WEBHOOK_PASSWORD")
    webapp_hmac_secret: str = Field(alias="WEBAPP_HMAC_SECRET")
    yforms_webhook_secret: Optional[str] = Field(default=None, alias="YFORMS_WEBHOOK_SECRET")

    # Planfix task configuration
    planfix_task_template_ids: Optional[str] = Field(default=None, alias="PLANFIX_TASK_TEMPLATE_IDS")
    status_done_id: Optional[int] = Field(default=None, alias="STATUS_DONE_ID")
    status_cancelled_id: Optional[int] = Field(default=None, alias="STATUS_CANCELLED_ID")
    result_field_id: Optional[int] = Field(default=None, alias="RESULT_FIELD_ID")
    result_files_field_id: Optional[int] = Field(default=None, alias="RESULT_FILES_FIELD_ID")
    # Custom fields for guest assignment
    guest_field_id: Optional[int] = Field(default=None, alias="GUEST_FIELD_ID")
    assignment_source_field_id: Optional[int] = Field(default=None, alias="ASSIGNMENT_SOURCE_FIELD_ID")
    # Custom fields for form results
    score_field_id: Optional[int] = Field(default=None, alias="SCORE_FIELD_ID")
    result_status_field_id: Optional[int] = Field(default=None, alias="RESULT_STATUS_FIELD_ID")
    session_id_field_id: Optional[int] = Field(default=None, alias="SESSION_ID_FIELD_ID")
    sync_status_field_id: Optional[int] = Field(default=None, alias="SYNC_STATUS_FIELD_ID")
    integration_comment_field_id: Optional[int] = Field(default=None, alias="INTEGRATION_COMMENT_FIELD_ID")

    # Server configuration
    webhook_host: str = Field(default="0.0.0.0", alias="WEBHOOK_HOST")
    webhook_port: int = Field(default=8001, alias="WEBHOOK_PORT")
    webhook_base_url: str = Field(default="http://crmbot.restme.pro", alias="WEBHOOK_BASE_URL")

    # Database
    database_path: str = Field(default="bot.db", alias="DATABASE_PATH")

    # Form URLs (comma-separated: resto_a,resto_b,resto_c,delivery_a,delivery_b,delivery_c)
    # Or with form codes: resto_a,resto_b,resto_c,delivery_adjika,delivery_hinkal,delivery_myasorub
    form_urls: Optional[str] = Field(default=None, alias="FORM_URLS")

    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }

    @property
    def task_template_ids_list(self) -> list[int]:
        """Parse task template IDs from comma-separated string."""
        if not self.planfix_task_template_ids:
            return []
        return [int(x.strip()) for x in self.planfix_task_template_ids.split(",") if x.strip()]

    @property
    def form_urls_dict(self) -> dict[str, str]:
        """Parse form URLs from comma-separated string."""
        if not self.form_urls:
            return {}
        urls = [x.strip() for x in self.form_urls.split(",") if x.strip()]
        # Support both old format and new format with form codes
        form_names = ["resto_a", "resto_b", "resto_c", "delivery_a", "delivery_b", "delivery_c"]
        base_dict = dict(zip(form_names, urls))
        
        # Add mappings for new form codes (delivery_adjika, delivery_hinkal, delivery_myasorub)
        form_code_mapping = {
            "delivery_adjika": "delivery_a",
            "delivery_hinkal": "delivery_b",
            "delivery_myasorub": "delivery_c",
        }
        for form_code, mapped_form in form_code_mapping.items():
            if mapped_form in base_dict:
                base_dict[form_code] = base_dict[mapped_form]
        
        return base_dict


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()

