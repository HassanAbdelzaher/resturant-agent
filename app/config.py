"""
Application configuration using pydantic-settings.
Loads from .env file or environment variables.
"""

from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    # ── GreenAPI WhatsApp Gateway ──────────────────────────────────
    # Get these from https://green-api.com → My Instances → your instance
    greenapi_id_instance: str = ""       # e.g. "1101234567"
    greenapi_api_token: str = ""         # e.g. "d75b3a66374942c5b3c6..."
    # GreenAPI REST base URL (change for EU/other regions if needed)
    greenapi_api_url: str = "https://api.green-api.com"
    greenapi_media_url: str = "https://media.green-api.com"

    # ── LLM Provider ──────────────────────────────────────────────
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # ── Database ──────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/bot.db"

    # ── Vector Store ──────────────────────────────────────────────
    chroma_persist_dir: str = "./data/chroma_db"

    # ── PDF Directory ─────────────────────────────────────────────
    pdf_directory: str = "./pdfs"

    # ── MCP ───────────────────────────────────────────────────────
    mcp_server_url: str = "http://localhost:3000"
    mcp_transport: Literal["stdio", "sse", "streamable-http"] = "stdio"

    # ── App ───────────────────────────────────────────────────────
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True

    # ── Order Management ──────────────────────────────────────────
    # WhatsApp ID to send new order notifications to (e.g. "966501234567")
    staff_wa_id: str = ""

    # ── Security & Rate Limiting ───────────────────────────────────
    # Comma-separated WhatsApp IDs allowed to run system commands
    # e.g. "966501234567,966509876543"
    admin_wa_ids: str = ""
    # Max messages per user per minute (0 = unlimited)
    rate_limit_per_minute: int = 20
    # Max PDF upload size in bytes (default 10 MB)
    pdf_max_size_bytes: int = 10 * 1024 * 1024

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def admin_ids_set(self) -> set[str]:
        """Return admin IDs as a set for fast lookup."""
        if not self.admin_wa_ids:
            return set()
        return {uid.strip() for uid in self.admin_wa_ids.split(",") if uid.strip()}


settings = Settings()
