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

from sqlalchemy import String, Text, DateTime, Integer, Float, select, func
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


class Order(Base):
    """A customer order placed via WhatsApp."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wa_id: Mapped[str] = mapped_column(String(50), index=True)
    user_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending / confirmed / cancelled
    total: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class OrderItem(Base):
    """A single dish line inside an Order."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    dish_id: Mapped[str] = mapped_column(String(50))
    dish_name: Mapped[str] = mapped_column(String(200))
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    subtotal: Mapped[float] = mapped_column(Float)


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

    # ── Order Management ───────────────────────────────────────────
    async def place_order(
        self,
        wa_id: str,
        items: list,  # list[CartItem]
        total: float,
        user_name: str = None,
        notes: str = None,
    ) -> "Order":
        """Persist a confirmed order and its items. Returns the saved Order."""
        async with self.async_session() as session:
            order = Order(
                wa_id=wa_id,
                user_name=user_name,
                total=total,
                notes=notes,
                status="confirmed",
            )
            session.add(order)
            await session.flush()  # get order.id before inserting items

            for item in items:
                session.add(
                    OrderItem(
                        order_id=order.id,
                        dish_id=item.dish_id,
                        dish_name=item.name,
                        price=item.price,
                        quantity=item.quantity,
                        subtotal=item.subtotal,
                    )
                )

            await session.commit()
            await session.refresh(order)
            return order

    async def get_user_orders(self, wa_id: str, limit: int = 5) -> list:
        """Return the most recent orders for a user."""
        async with self.async_session() as session:
            result = await session.execute(
                select(Order)
                .where(Order.wa_id == wa_id)
                .order_by(Order.created_at.desc())
                .limit(limit)
            )
            return result.scalars().all()

    # ── Natural Language SQL Query (for agent use) ─────────────────
    async def execute_raw_query(self, query: str) -> list[dict]:
        """
        Execute a read-only SQL query (SELECT only, for safety).
        Used by the agent to answer data questions.

        Validates that the statement is a plain SELECT with no stacked
        statements, sub-commands, or DDL/DML keywords.
        """
        from sqlalchemy import text as sa_text
        import re

        normalized = query.strip()

        # Must start with SELECT
        if not normalized.upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed.")

        # Block stacked statements and dangerous keywords
        _BLOCKED = re.compile(
            r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE"
            r"|GRANT|REVOKE|ATTACH|DETACH|PRAGMA)\b",
            re.IGNORECASE,
        )
        if _BLOCKED.search(normalized):
            raise ValueError("Query contains disallowed SQL keywords.")

        # Block multiple statements (simple semicolon check)
        # Allow semicolon only as the very last character (optional terminator)
        core = normalized.rstrip(";").rstrip()
        if ";" in core:
            raise ValueError("Multiple statements are not allowed.")

        async with self.async_session() as session:
            result = await session.execute(sa_text(normalized))
            rows = result.fetchall()
            columns = list(result.keys())
            return [dict(zip(columns, row)) for row in rows]
