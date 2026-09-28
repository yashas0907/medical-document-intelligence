"""Application configuration via environment variables (12-factor)."""
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MB = 1024 * 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "MedIntel"
    app_env: Literal["dev", "staging", "prod"] = "dev"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # Database
    database_url: str = "sqlite:///./data/app.db"

    # Security
    secret_key: str = "dev-insecure-secret-key-change-me"
    access_token_expire_minutes: int = 120
    demo_user_email: str = "demo@medintel.local"
    demo_user_password: str = "demo-password"

    # Uploads
    max_upload_mb: int = 30
    storage_root: str = "./storage"
    allowed_extensions: str = ".pdf,.docx,.txt"
    retention_days: int = 90

    # Processing
    worker_concurrency: int = 2
    max_pages_per_doc: int = 120
    max_pages_ocr: int = 40

    # Embeddings
    embedding_provider: Literal["local", "openai"] = "local"
    embedding_model: str = "medintel-tfidf-v1"
    embedding_api_base: str | None = None
    embedding_api_key: str | None = None

    # LLM
    llm_provider: Literal["none", "openai-compatible"] = "none"
    llm_model: str | None = None
    llm_api_base: str | None = None
    llm_api_key: str | None = None

    # OCR
    ocr_provider: str = "auto"  # auto | none
    tesseract_cmd: str | None = None

    # Rate limits
    rate_limit_upload_per_min: int = 10
    rate_limit_ai_per_min: int = 20
    rate_limit_auth_per_min: int = 20

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError("log_level must be one of DEBUG|INFO|WARNING|ERROR")
        return v

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * MB

    @property
    def allowed_ext_list(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_extensions.split(",") if e.strip()}

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "none" and bool(self.llm_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
