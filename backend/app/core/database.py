import os
import sqlite3
import sys
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.core.config import settings

# If running under pytest, clean stale database file on module import for clean test run
if "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ:
    test_db = Path("./tickets.db")
    if test_db.exists():
        try:
            test_db.unlink()
        except Exception:
            pass


def _configure_sqlite_boolean_types() -> None:
    """Make SQLite BOOLEAN columns round-trip as Python ``bool``.

    SQLite stores booleans as integers 0/1. By registering a ``BOOLEAN``
    converter and enabling sqlite3's declared-type detection on every
    aiosqlite connection, raw SQL reads of ``BOOLEAN`` columns return proper
    ``True``/``False`` values. This keeps ``decision_log.auto_resolved``
    consistent whether it is read through the ORM or via plain SQL.
    """
    if "BOOLEAN" not in sqlite3.converters:
        sqlite3.register_converter("BOOLEAN", lambda value: value == b"1")

    import aiosqlite

    _original_connect = aiosqlite.connect

    if getattr(_original_connect, "_stm_configured", False):
        return

    def _connect_with_decltypes(*args, **kwargs):
        kwargs.setdefault(
            "detect_types", sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        return _original_connect(*args, **kwargs)

    _connect_with_decltypes._stm_configured = True  # type: ignore[attr-defined]
    aiosqlite.connect = _connect_with_decltypes


_configure_sqlite_boolean_types()

engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def init_db() -> None:
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides an async database session."""
    async with AsyncSessionLocal() as session:
        yield session
