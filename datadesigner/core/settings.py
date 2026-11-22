"""Settings from .env (pydantic-settings). Values equal to __ASK_USER__ count as missing (plan §3.1C)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import SecretMissing

ROOT = Path(__file__).resolve().parents[2]
ASK = "__ASK_USER__"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore", case_sensitive=False)

    crustdata_api_key: str = ""
    crustdata_api_version: str = "2025-11-01"
    crustdata_base_url: str = "https://api.crustdata.com"
    dd_anthropic_api_key: str = ""
    claude_model_classify: str = "auto"
    claude_model_reason: str = "auto"
    claude_model_adversarial: str = "auto"
    claude_model_judge: str = "auto"
    llm_max_retries: int = 4
    llm_timeout_s: float = 90
    gmail_address: str = ""
    gmail_app_password: str = ""
    test_inbox: str = ""
    mail_provider: str = "mailpit"
    mail_mode: str = "test"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    mail_daily_cap: int = 50
    mailpit_smtp_port: int = 1025
    mailpit_api: str = "http://localhost:8025"
    dd_http_mode: str = "replay"
    dd_env: str = "dev"
    dd_tz: str = "Asia/Kolkata"
    dd_db: str = "data/datadesigner.sqlite"
    dd_frozen_now: str = ""
    dd_cassette: str = "default"

    def secret(self, name: str) -> str:
        """Return a secret or raise SecretMissing (never prints the value)."""
        v = getattr(self, name, "") or ""
        if not v or v == ASK or v == "cd_xxx":
            raise SecretMissing(f"{name.upper()} is not set — run /setup-secrets (make setup-secrets)")
        return v.replace(" ", "") if name == "gmail_app_password" else v

    def present(self) -> dict[str, bool]:
        """Booleans only, for GET /setup/status."""
        out = {}
        for k in ["crustdata_api_key", "dd_anthropic_api_key", "gmail_address", "gmail_app_password", "test_inbox"]:
            v = getattr(self, k, "")
            out[k.upper()] = bool(v) and v not in (ASK, "cd_xxx")
        return out

    @property
    def db_path(self) -> Path:
        p = Path(self.dd_db)
        return p if p.is_absolute() else ROOT / p


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    get_settings.cache_clear()


def http_mode() -> str:
    return os.environ.get("DD_HTTP_MODE") or get_settings().dd_http_mode
