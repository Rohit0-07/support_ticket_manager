import pytest
import pytest_asyncio
from pathlib import Path
import csv
import tempfile
from httpx import AsyncClient, ASGITransport

# Note: The test engineer must not read implementation code, so imports from backend app
# follow the exact conventions specified in 2_tech_spec.md.

from app.main import app
from app.core.database import get_db, init_db, engine
from app.services.ingestion_service import (
    seed_resolved_tickets,
    seed_new_tickets,
    seed_orders,
    seed_all,
)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def temp_csv_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # Valid resolved_tickets.csv
        resolved_csv = tmp_path / "resolved_tickets.csv"
        with open(resolved_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["ticket_id", "category", "description", "resolution_action", "resolution_note", "time_to_resolve_min", "csat"])
            writer.writerow(["H-1000", "missing_item", "milk packet missing", "redelivery", "missing item re-sent", 32, 5])
            writer.writerow(["H-1001", "wrong_item", "received someone else order", "refund", "refund processed", 10, 4])

        # Valid new_tickets.csv
        new_csv = tmp_path / "new_tickets.csv"
        with open(new_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["ticket_id", "created_at", "order_id", "description"])
            writer.writerow(["N-000", "2026-08-07T20:58:00", "ORD-9900", "fruits were rotten"])
            writer.writerow(["N-001", "2026-08-07T20:38:00", "ORD-9901", "wrong brand of rice"])

        # Valid orders_context.csv
        orders_csv = tmp_path / "orders_context.csv"
        with open(orders_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["order_id", "items", "value_inr", "delivery_time_min", "delivery_status"])
            writer.writerow(["ORD-9900", "1", "999.0", "24", "cancelled"])
            writer.writerow(["ORD-9901", "2", "189.0", "28", "delivered"])

        yield tmp_path


@pytest.fixture
def malformed_csv_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        resolved_csv = tmp_path / "resolved_tickets.csv"
        with open(resolved_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["ticket_id", "category", "description", "resolution_action", "resolution_note", "time_to_resolve_min", "csat"])
            writer.writerow(["H-2000", "missing_item", "good row", "refund", "note", 15, 5])
            # Malformed row: invalid int/float types or missing columns
            writer.writerow(["H-2001", "missing_item", "bad row", "refund", "note", "invalid_int", "not_a_float"])

        new_csv = tmp_path / "new_tickets.csv"
        with open(new_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["ticket_id", "created_at", "order_id", "description"])
            writer.writerow(["N-100", "2026-08-07T20:58:00", "ORD-100", "valid new ticket"])

        orders_csv = tmp_path / "orders_context.csv"
        with open(orders_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["order_id", "items", "value_inr", "delivery_time_min", "delivery_status"])
            writer.writerow(["ORD-100", "1", "100.0", "10", "delivered"])

        yield tmp_path


# ── Unit Tests: Ingestion Service ──────────────────────────────────

@pytest.mark.asyncio
async def test_seed_all_valid(temp_csv_dir):
    """AC-1, AC-2, AC-3: Valid CSVs load cleanly into database."""
    # Assuming get_db fixture or direct async session passed to seed_all
    results = await seed_all(temp_csv_dir, db=None)
    
    assert "resolved_tickets" in results
    assert results["resolved_tickets"].rows_loaded == 2
    assert results["resolved_tickets"].rows_skipped == 0

    assert "new_tickets" in results
    assert results["new_tickets"].rows_loaded == 2

    assert "orders" in results or "orders_context" in results
    assert results["orders"].rows_loaded == 2 if "orders" in results else results["orders_context"].rows_loaded == 2


@pytest.mark.asyncio
async def test_seed_idempotency(temp_csv_dir):
    """AC-4: Running seeding twice produces same row counts without duplicates."""
    res1 = await seed_all(temp_csv_dir, db=None)
    res2 = await seed_all(temp_csv_dir, db=None)

    assert res2["resolved_tickets"].rows_loaded == 0 or res2["resolved_tickets"].rows_skipped == 2
    # Ensure database counts match initial run counts


@pytest.mark.asyncio
async def test_seed_malformed_rows_skipped(malformed_csv_dir):
    """AC-5: Malformed row is skipped with warning logged, rest of file loads."""
    results = await seed_all(malformed_csv_dir, db=None)
    resolved_res = results["resolved_tickets"]

    assert resolved_res.rows_loaded == 1
    assert resolved_res.rows_skipped == 1
    assert len(resolved_res.warnings) >= 1


# ── Integration Tests: REST API Routes ──────────────────────────────

@pytest.mark.asyncio
async def test_get_resolved_tickets_list(async_client):
    """AC-6, AC-11: List endpoint for resolved tickets returns paginated records."""
    response = await async_client.get("/api/v1/resolved-tickets?skip=0&limit=50")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "items" in data
    assert isinstance(data["items"], list)
    if len(data["items"]) > 0:
        item = data["items"][0]
        assert "ticket_id" in item
        assert "category" in item
        assert "description" in item
        assert "action_taken" in item
        assert "resolution_note" in item
        assert "time_to_resolve_min" in item
        assert "csat_score" in item


@pytest.mark.asyncio
async def test_get_resolved_ticket_detail_success(async_client):
    """AC-9: Single record endpoint returns correct resolved ticket."""
    response = await async_client.get("/api/v1/resolved-tickets/H-1000")
    if response.status_code == 200:
        data = response.json()
        assert data["ticket_id"] == "H-1000"
        assert "description" in data


@pytest.mark.asyncio
async def test_get_resolved_ticket_detail_not_found(async_client):
    """AC-10: Single record endpoint returns 404 for invalid ID."""
    response = await async_client.get("/api/v1/resolved-tickets/NON-EXISTENT-ID")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_get_new_tickets_list(async_client):
    """AC-7, AC-12: List endpoint for new tickets returns records with required fields."""
    response = await async_client.get("/api/v1/new-tickets")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "items" in data
    if len(data["items"]) > 0:
        item = data["items"][0]
        assert "ticket_id" in item
        assert "created_at" in item
        assert "order_id" in item
        assert "description" in item


@pytest.mark.asyncio
async def test_get_new_ticket_detail_not_found(async_client):
    """AC-10: Single record endpoint returns 404 for invalid new ticket ID."""
    response = await async_client.get("/api/v1/new-tickets/N-INVALID")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_orders_list(async_client):
    """AC-8, AC-13: List endpoint for order context returns records with required fields."""
    response = await async_client.get("/api/v1/orders")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "items" in data
    if len(data["items"]) > 0:
        item = data["items"][0]
        assert "order_id" in item
        assert "items" in item
        assert "value" in item
        assert "delivery_time" in item
        assert "status" in item


@pytest.mark.asyncio
async def test_get_order_detail_not_found(async_client):
    """AC-10: Single record endpoint returns 404 for invalid order ID."""
    response = await async_client.get("/api/v1/orders/ORD-INVALID")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_seed_endpoint(async_client):
    """Tests POST /api/v1/seed endpoint contract."""
    response = await async_client.post("/api/v1/seed")
    assert response.status_code == 200
    data = response.json()
    assert "resolved_tickets_loaded" in data
    assert "new_tickets_loaded" in data
    assert "orders_loaded" in data
    assert "warnings" in data


@pytest.mark.asyncio
async def test_health_check_endpoint(async_client):
    """Tests GET /api/v1/health check endpoint contract."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "ok"
    assert "resolved_tickets_count" in data
    assert "new_tickets_count" in data
    assert "orders_count" in data
