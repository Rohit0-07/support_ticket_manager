import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, init_db
from app.models.db_models import ResolvedTicket, NewTicket, OrderContext

logger = logging.getLogger(__name__)


@dataclass
class SeedResult:
    """Result of a seeding operation for a single CSV."""
    table_name: str
    rows_loaded: int = 0
    rows_skipped: int = 0
    warnings: list[str] = field(default_factory=list)


def _find_csv(csv_dir: Path, target_name: str, patterns: list[str]) -> Optional[Path]:
    """Locate a CSV file by standard name or fallback pattern match."""
    exact = csv_dir / target_name
    if exact.exists():
        return exact
    
    for pattern in patterns:
        matches = list(csv_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


async def seed_resolved_tickets(csv_path: Path, db=None) -> SeedResult:
    """
    Parse resolved_tickets.csv and load into resolved_tickets table.
    Returns counts and warnings for skipped rows.
    """
    await init_db()
    result = SeedResult(table_name="resolved_tickets")

    if not csv_path or not csv_path.exists():
        msg = f"CSV file not found: {csv_path}"
        logger.warning(msg)
        result.warnings.append(msg)
        return result

    should_close = False
    if db is None:
        db = AsyncSessionLocal()
        should_close = True

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for line_no, row in enumerate(reader, start=2):
                try:
                    ticket_id = (row.get("ticket_id") or "").strip()
                    category = (row.get("category") or "").strip()
                    description = (row.get("description") or "").strip()
                    action_taken = (row.get("resolution_action") or row.get("action_taken") or "").strip()
                    resolution_note = (row.get("resolution_note") or "").strip()
                    
                    if not ticket_id or not category or not description or not action_taken or not resolution_note:
                        raise ValueError(f"Line {line_no}: Missing required string fields")

                    time_to_resolve = int(row.get("time_to_resolve_min"))
                    csat_val = row.get("csat") if row.get("csat") is not None else row.get("csat_score")
                    csat = float(csat_val)

                    # Check for duplicate
                    existing = await db.get(ResolvedTicket, ticket_id)
                    if existing:
                        result.rows_skipped += 1
                        continue

                    ticket = ResolvedTicket(
                        ticket_id=ticket_id,
                        category=category,
                        description=description,
                        action_taken=action_taken,
                        resolution_note=resolution_note,
                        time_to_resolve_min=time_to_resolve,
                        csat_score=csat,
                    )
                    db.add(ticket)
                    result.rows_loaded += 1
                except (ValueError, TypeError, KeyError) as e:
                    warn_msg = f"Line {line_no}: Skipped malformed row in resolved_tickets: {e}"
                    logger.warning(warn_msg)
                    result.warnings.append(warn_msg)
                    result.rows_skipped += 1

        await db.commit()
    finally:
        if should_close:
            await db.close()

    return result


async def seed_new_tickets(csv_path: Path, db=None) -> SeedResult:
    """
    Parse new_tickets.csv and load into new_tickets table.
    Returns counts and warnings for skipped rows.
    """
    await init_db()
    result = SeedResult(table_name="new_tickets")

    if not csv_path or not csv_path.exists():
        msg = f"CSV file not found: {csv_path}"
        logger.warning(msg)
        result.warnings.append(msg)
        return result

    should_close = False
    if db is None:
        db = AsyncSessionLocal()
        should_close = True

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for line_no, row in enumerate(reader, start=2):
                try:
                    ticket_id = (row.get("ticket_id") or "").strip()
                    created_at = (row.get("created_at") or "").strip()
                    order_id = (row.get("order_id") or "").strip()
                    description = (row.get("description") or "").strip()

                    if not ticket_id or not created_at or not order_id or not description:
                        raise ValueError(f"Line {line_no}: Missing required string fields")

                    existing = await db.get(NewTicket, ticket_id)
                    if existing:
                        result.rows_skipped += 1
                        continue

                    ticket = NewTicket(
                        ticket_id=ticket_id,
                        created_at=created_at,
                        order_id=order_id,
                        description=description,
                    )
                    db.add(ticket)
                    result.rows_loaded += 1
                except (ValueError, TypeError, KeyError) as e:
                    warn_msg = f"Line {line_no}: Skipped malformed row in new_tickets: {e}"
                    logger.warning(warn_msg)
                    result.warnings.append(warn_msg)
                    result.rows_skipped += 1

        await db.commit()
    finally:
        if should_close:
            await db.close()

    return result


async def seed_orders(csv_path: Path, db=None) -> SeedResult:
    """
    Parse orders_context.csv and load into orders_context table.
    Returns counts and warnings for skipped rows.
    """
    await init_db()
    result = SeedResult(table_name="orders_context")

    if not csv_path or not csv_path.exists():
        msg = f"CSV file not found: {csv_path}"
        logger.warning(msg)
        result.warnings.append(msg)
        return result

    should_close = False
    if db is None:
        db = AsyncSessionLocal()
        should_close = True

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for line_no, row in enumerate(reader, start=2):
                try:
                    order_id = (row.get("order_id") or "").strip()
                    items = (row.get("items") or "").strip()
                    val = float(row.get("value_inr") if row.get("value_inr") is not None else row.get("value"))
                    delivery_time = str(row.get("delivery_time_min") if row.get("delivery_time_min") is not None else row.get("delivery_time")).strip()
                    status = (row.get("delivery_status") or row.get("status") or "").strip()

                    if not order_id or not items or not delivery_time or not status:
                        raise ValueError(f"Line {line_no}: Missing required fields")

                    existing = await db.get(OrderContext, order_id)
                    if existing:
                        result.rows_skipped += 1
                        continue

                    order = OrderContext(
                        order_id=order_id,
                        items=items,
                        value=val,
                        delivery_time=delivery_time,
                        status=status,
                    )
                    db.add(order)
                    result.rows_loaded += 1
                except (ValueError, TypeError, KeyError) as e:
                    warn_msg = f"Line {line_no}: Skipped malformed row in orders_context: {e}"
                    logger.warning(warn_msg)
                    result.warnings.append(warn_msg)
                    result.rows_skipped += 1

        await db.commit()
    finally:
        if should_close:
            await db.close()

    return result


async def seed_all(csv_dir: Path, db=None) -> Dict[str, SeedResult]:
    """
    Convenience function to seed all three tables from csv_dir.
    Returns dict mapping table name -> SeedResult.
    """
    resolved_path = _find_csv(csv_dir, "resolved_tickets.csv", ["*RESOLV*", "*resolved*"])
    new_path = _find_csv(csv_dir, "new_tickets.csv", ["*NEW_TI*", "*new*"])
    orders_path = _find_csv(csv_dir, "orders_context.csv", ["*ORDERS*", "*orders*"])

    res_resolved = await seed_resolved_tickets(resolved_path, db=db)
    res_new = await seed_new_tickets(new_path, db=db)
    res_orders = await seed_orders(orders_path, db=db)

    return {
        "resolved_tickets": res_resolved,
        "new_tickets": res_new,
        "orders": res_orders,
        "orders_context": res_orders,
    }
