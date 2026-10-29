from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    database_url: str = "postgresql://agentgrid:agentgrid@127.0.0.1:5432/agentgrid"
    jwt_secret: str = "dev-only-change-me"  # noqa: S105 - dev default; production sets JWT_SECRET
    # Fernet master key (urlsafe base64, 32 bytes). Wraps per-tenant data keys; KMS in the target architecture.
    master_key: str = ""
    # Public URL of this API (Telegram webhooks, widget snippet). Render sets RENDER_EXTERNAL_URL automatically.
    public_api_url: str = Field("http://localhost:8000", validation_alias=AliasChoices("PUBLIC_API_URL", "RENDER_EXTERNAL_URL"))
    console_url: str = "http://localhost:5173"
    access_token_minutes: int = 60
    refresh_token_days: int = 7

    # Platform-default LLM (used when a tenant has not brought its own). Empty key → offline demo model.
    llm_provider: str = "openrouter"  # openai | anthropic | openrouter | qwen | ollama | openai_compat
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "anthropic/claude-sonnet-4.5"
    llm_cheap_model: str = "openai/gpt-4o-mini"
    llm_timeout_s: int = 45

    embeddings: str = "fastembed"  # fastembed | openai | none (none → full-text search only)
    embeddings_api_key: str = ""
    embeddings_base_url: str = ""
    embeddings_model: str = "text-embedding-3-small"
    fastembed_cache: str = str(BACKEND_DIR / ".data" / "fastembed")
    retrieval_min_similarity: float = 0.60

    whatsapp_graph_version: str = "v23.0"
    telegram_polling: bool | None = None  # None → poll when public_api_url is not https (local dev)

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "AgentGrid <no-reply@agentgrid.local>"

    demo_password: str = "AgentGrid#Demo2026"  # noqa: S105 - public demo accounts, shared on purpose
    seed_on_empty: bool = True
    job_concurrency: int = 8
    log_level: str = "INFO"


@lru_cache
def settings() -> Settings:
    return Settings()
