"""Shared pytest fixtures for F7 Live Ticket Simulation tests (FEAT-007).

These fixtures are built ONLY from the contracts documented in
`features/F7-live-ticket-simulation/2_tech_spec.md`:

- §1.5/§2.2: service + engine + manager live under ``backend/app``
  (imports ``app.*``).
- §3.1: F7 introduces no tables of its own; the in-memory schema mirrors the
  F1/F3/F4 tables it consumes (``new_tickets``, ``decision_log``,
  ``reply_log``, ``resolved_tickets``).
- §4.1..§4.5: endpoint paths, methods, and status codes under
  ``/api/v1/simulation``.

The DB is an isolated in-memory SQLite. ``get_db`` is overridden so endpoint
tests exercise the full route → service → DB path without touching a real
database. ``reset_simulation_manager()`` is invoked before and after every
test so the single-flight runtime never leaks state across cases (per
`2_tech_spec.md` §8 note 1).
"""

import sys
from pathlib import Path

import httpx
import pytest
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
from app.services.simulation_service import reset_simulation_manager  # noqa: E402

# Schema mirroring `2_tech_spec.md` §3 — the F1/F3/F4 tables F7 consumes.
# F7 itself introduces no new tables (BR-04).
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
"""


@pytest_asyncio.fixture
async def db_engine():
    """In-memory async SQLite engine with the F1/F3/F4 tables F7 consumes."""
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

    ``get_db`` is overridden (per §2.2 route dependency) so all endpoint
    tests run against the isolated in-memory DB described above.
    """

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _clean_simulation_manager():
    """Guarantee a clean single-flight runtime between every test case.

    The ``SimulationManager`` is a module-level singleton (2_tech_spec.md
    §1.2); without resetting it, lifecycle state and background tasks would
    leak across cases. Per §8 note 1: call ``reset_simulation_manager()``
    between test cases.
    """
    reset_simulation_manager()
    yield
    reset_simulation_manager()
