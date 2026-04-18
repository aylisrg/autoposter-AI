"""App configuration loaded from .env via pydantic-settings."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime config. Loaded from ../.env at project root."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM keys
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    # Backend
    backend_port: int = 8787
    db_url: str = "sqlite:///./data/app.db"

    # Models
    text_model: str = "claude-sonnet-4-6"
    image_model: str = "gemini-2.5-flash-image"
    enable_image_gen: bool = True

    # Scraper
    playwright_headless: bool = True

    # Safety
    min_delay_between_posts_sec: int = 120
    max_delay_between_posts_sec: int = 300
    max_posts_per_day: int = 50


settings = Settings()
