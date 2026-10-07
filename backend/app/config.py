"""Central, typed configuration. The ONLY module that reads environment variables.

Every other module does:  from app.config import settings
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/.env, resolved from this file's location so it works from any cwd.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # Least privilege: two DB identities.
    #   DATABASE_URL        -> read-only role. Used by the chatbot + MCP server.
    #   OWNER_DATABASE_URL  -> write role. Used ONLY by setup/ingestion scripts.
    database_url: str
    owner_database_url: str

    anthropic_api_key: str
    llm_model: str = "claude-haiku-4-5-20251001"

    # --- API / session settings (all optional; safe defaults for local development)
    # If SESSION_SECRET is not set, a random one is generated at startup (sessions then reset on restart).
    session_secret: str | None = None
    session_hours: int = 8
    cookie_secure: bool = False                       # set True behind HTTPS in production
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"   # the React dev server

    # Our tables are prefixed so they never collide with your other project's tables.
    table_prefix: str = "hc_"

    # Pydantic matches env var names case-insensitively (DATABASE_URL -> database_url).
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    def __repr__(self) -> str:  # never print secrets by accident
        return "Settings(<secrets hidden>)"

    __str__ = __repr__


# Instantiating at import time = fail fast: a missing variable crashes startup
# with a clear validation error instead of failing mid-conversation.
settings = Settings()
