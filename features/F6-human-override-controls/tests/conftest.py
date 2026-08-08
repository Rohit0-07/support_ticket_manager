"""Shared pytest fixtures for F6 Human Override Controls tests (FEAT-006).

These fixtures are built ONLY from the contracts documented in
`features/F6-human-override-controls/2_tech_spec.md`:

- §2.3/§2.4: service + route live under ``backend/app`` (imports ``app.*``).
- §3.1: the F1/F3/F4 tables consumed by F6 (decision_log, new_tickets,
  reply_log, orders_context) plus F6's own ``human_decision_log``.
- §4.1..§4.5: endpoint paths, methods, and status codes.

The DB is an isolated in-memory SQLite whose schema mirrors the consumed
tables documented in `2_tech_spec.md` §3.1 (and the F5 test harness, since F6
extends the F5 dashboard). ``get_db`` is overridden so endpoint tests exercise
the full route -> service -> DB path without touching a real database and
without depending on how the application constructs its production engine.
"""

import sys
from pathlib import Path

import httpx
import pytest_asyncio

BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.database import get_db  # noqa: E402
from app.main import app  # noqa: E402

# Schema mirroring `2_tech_spec.md` §3.1 — the F1/F3/F4 tables F6 consumes,
# plus the F6-owned human_decision_log (PK ticket_id = one-decision invariant).
TEST_SCHEMA = """
CREATE TABLE decision_log (
    ticket_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    action TEXT,
    confidence REAL NOT NULL,
    auto_resolved BOOLEAN NOT NULL,
    escalation_reason TEXT,
    similar_ticket_ids TEXT,
    reasoning TEXT NOT NULL,
    refund_amount REAL,
    created_at TEXT NOT NULL
);
CREATE TABLE new_tickets (
    ticket_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    description TEXT NOT NULL
);
CREATE TABLE reply_log (
    ticket_id TEXT PRIMARY KEY,
    variant TEXT NOT NULL,
    final_body TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE resolved_tickets (
    ticket_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    action_taken TEXT NOT NULL,
    resolution_note TEXT NOT NULL
);
CREATE TABLE orders_context (
    order_id TEXT PRIMARY KEY,
    status TEXT,
    value REAL
);
CREATE TABLE human_decision_log (
    ticket_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    agent_action TEXT NOT NULL,
    original_action TEXT,
    final_action TEXT,
    rejection_reason TEXT,
    final_reply TEXT,
    agent_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


@pytest_asyncio.fixture
async def db_engine():
    """In-memory async SQLite engine with the F1/F3/F4 + F6 tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        for statement in TEST_SCHEMA.split(";"):
            statement = statement.strip()
            if statement:
                await conn.execute(text(statement))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """AsyncSession bound to the isolated test DB."""
    session_factory = sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    """httpx AsyncClient mounted on the app with the test DB injected.

    ``get_db`` is overridden (per §2.4 route dependency) so all endpoint
    tests run against the isolated in-memory DB described above.
    """

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)
