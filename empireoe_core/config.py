"""Base settings class for all Empire backends.

Product backends extend this with their own settings:

    class Settings(EmpireBaseSettings):
        PRODUCT_SPECIFIC_KEY: str = ""
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class EmpireBaseSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    # Database
    DATABASE_URL: str = ""
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30

    # Security
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Auth
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""

    # App
    APP_NAME: str = "Empire Backend"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    def validate_required(self) -> list[str]:
        issues: list[str] = []
        if not self.DATABASE_URL:
            issues.append("DATABASE_URL is required")
        if not self.SECRET_KEY or len(self.SECRET_KEY) < 32:
            issues.append("SECRET_KEY must be at least 32 characters")
        return issues
