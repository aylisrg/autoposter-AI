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

    # M7 — Meta (Instagram + Threads) OAuth
    # Values come from the Facebook Developers console (Meta App). All
    # optional — the IG/Threads platforms just refuse to publish if the
    # corresponding long-lived token isn't set.
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_redirect_uri: str = "http://localhost:8787/api/meta/oauth/callback"
    # Long-lived user access token — populated via the /api/meta/oauth/callback
    # flow; we persist it on the PlatformCredential row too, but keep this
    # setting as an escape hatch for CLI users who'd rather paste a token.
    meta_access_token: str = ""
    # The Instagram Business Account id (numeric). One per Meta App; if the
    # user has multiple we pick the first unless they override.
    instagram_account_id: str = ""
    # The Threads user id (numeric).
    threads_user_id: str = ""

    # M8 — Security
    # Empty = auth disabled (single-user localhost default). Set to any
    # 4–32 char string to require `X-Dashboard-Pin` or a `/api/auth/login`
    # cookie on every /api/* request.
    dashboard_pin: str = ""
    # Fernet key for encryption-at-rest (44-char urlsafe base64). Empty = we
    # auto-generate one into `data/.fernet.key` and use that.
    fernet_key: str = ""

    # M8 — Backups
    backup_dir: str = "data/backups"
    backup_keep_days: int = 14


settings = Settings()
