"""
Database Layer — Async SQLAlchemy for conversation history and user management.

Supports:
  - SQLite (development) via aiosqlite
  - PostgreSQL (production) via asyncpg

Also provides a natural-language-to-SQL query interface for the agent.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Text, DateTime, Integer, select, func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings

logger = logging.getLogger(__name__)


# ── SQLAlchemy Base ───────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Models ────────────────────────────────────────────────────────
class User(Base):
    """Tracks WhatsApp users who interact with the bot."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wa_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_active: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    message_count: Mapped[int] = mapped_column(Integer, default=0)


class Conversation(Base):
    """Stores conversation history for context retention."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wa_id: Mapped[str] = mapped_column(String(50), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" or "assistant"
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    source: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # "pdf", "db", "mcp"


class Document(Base):
    """Tracks ingested PDF documents."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(500))
    file_path: Mapped[str] = mapped_column(String(1000))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


# ── Database Manager ──────────────────────────────────────────────
class DatabaseManager:
    """Manages async database connections and provides query methods."""

    def __init__(self, database_url: str = None):
        self.database_url = database_url or settings.database_url
        self.engine = create_async_engine(self.database_url, echo=settings.debug)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init_db(self):
        """Create all tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created")

    async def close(self):
        """Close the database engine."""
        await self.engine.dispose()

    # ── User Operations ────────────────────────────────────────────
    async def get_or_create_user(self, wa_id: str, name: str = None) -> User:
        """Get existing user or create a new one."""
        async with self.async_session() as session:
            result = await session.execute(select(User).where(User.wa_id == wa_id))
            user = result.scalar_one_or_none()

            if not user:
                user = User(wa_id=wa_id, name=name)
                session.add(user)
            else:
                user.last_active = datetime.now(timezone.utc)
                user.message_count += 1

            await session.commit()
            await session.refresh(user)
            return user

    # ── Conversation History ───────────────────────────────────────
    async def save_message(
        self, wa_id: str, role: str, content: str, source: str = None
    ):
        """Save a message to conversation history."""
        async with self.async_session() as session:
            msg = Conversation(
                wa_id=wa_id, role=role, content=content, source=source
            )
            session.add(msg)
            await session.commit()

    async def get_conversation_history(
        self, wa_id: str, limit: int = 10
    ) -> list[dict]:
        """Get recent conversation history for context."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Conversation)
                .where(Conversation.wa_id == wa_id)
                .order_by(Conversation.timestamp.desc())
                .limit(limit)
            )
            messages = result.scalars().all()

            return [
                {"role": msg.role, "content": msg.content}
                for msg in reversed(messages)
            ]

    # ── Document Tracking ──────────────────────────────────────────
    async def track_document(
        self, filename: str, file_path: str, chunk_count: int
    ) -> Document:
        """Record an ingested document."""
        async with self.async_session() as session:
            doc = Document(
                filename=filename, file_path=file_path, chunk_count=chunk_count
            )
            session.add(doc)
            await session.commit()
            await session.refresh(doc)
            return doc

    async def get_documents(self) -> list[Document]:
        """List all tracked documents."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Document).order_by(Document.ingested_at.desc())
            )
            return result.scalars().all()

    # ── Stats ──────────────────────────────────────────────────────
    async def get_stats(self) -> dict:
        """Get database statistics."""
        async with self.async_session() as session:
            user_count = await session.scalar(select(func.count(User.id)))
            msg_count = await session.scalar(select(func.count(Conversation.id)))
            doc_count = await session.scalar(select(func.count(Document.id)))

            return {
                "users": user_count or 0,
                "messages": msg_count or 0,
                "documents": doc_count or 0,
            }

    # ── Natural Language SQL Query (for agent use) ─────────────────
    async def execute_raw_query(self, query: str) -> list[dict]:
        """
        Execute a raw SQL query (SELECT only, for safety).
        Used by the agent to answer data questions.
        """
        if not query.strip().upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed for safety.")

        async with self.async_session() as session:
            result = await session.execute(query)
            rows = result.fetchall()
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]
