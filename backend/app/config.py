"""Settings, loaded from the environment and the repo-root `.env` (see `.env.example`)."""

from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_DATABASE_URL = f"sqlite+aiosqlite:///{BACKEND_DIR / 'data' / 'umessage.db'}"


class DatabaseSettings(BaseSettings):
    """The part of the settings Alembic needs; it must not require API_TOKEN."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = DEFAULT_DATABASE_URL


class Settings(DatabaseSettings):
    api_token: SecretStr = Field(min_length=16)
    umessage_mode: Literal["real", "demo"] = "real"
    user_timezone: str = "UTC"
    frontend_url: str = "http://127.0.0.1:3000"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    beeper_api_url: str = "http://127.0.0.1:23373"
    demo_beeper_running: bool = True
    # How often new Messages are fetched from the Message Source (seconds).
    new_messages_poll_seconds: float = Field(default=3.0, gt=0)
    # Demo mode only: about how often a scripted fixture Message arrives (seconds; 0 = never).
    demo_new_message_seconds: float = Field(default=30.0, ge=0)
    # Plan detection (ADR-0005): the Gemini API key (empty: detection is off in real mode)
    # and model.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash"
    # How long a Chat must be quiet after a new Message before it is checked for plans (s).
    plan_settle_seconds: float = Field(default=60.0, ge=0)
    # Plan Model decisions less confident than this (0-1) create or change nothing.
    plan_confidence_threshold: float = Field(default=0.5, ge=0, le=1)
    # At most this many Plan Model calls at a time.
    plan_max_concurrent: int = Field(default=2, ge=1)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("user_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {value!r}") from exc
        return value

    @property
    def allowed_origins(self) -> list[str]:
        return list(dict.fromkeys([self.frontend_url, *self.cors_origins]))
