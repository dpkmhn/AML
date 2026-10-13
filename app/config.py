"""Settings loaded from .env. Every module imports `settings` from here."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Admin connection: schema, data loading, resets
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5433/aml"
    # Copilot tools read through this role (SELECT only)
    database_url_ro: str = "postgresql+psycopg://copilot_ro:copilot_ro@localhost:5433/aml"
    # Cases and audit log are written through this role
    database_url_rw: str = "postgresql+psycopg://copilot_rw:copilot_rw@localhost:5433/aml"

    openai_api_key: SecretStr | None = None
    model_small: str
    model_strong: str
    embed_model: str
    embed_dim: int = 1536
    prompt_version: int = 1
    langsmith_api_key: SecretStr | None = None


settings = Settings()
