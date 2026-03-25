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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
