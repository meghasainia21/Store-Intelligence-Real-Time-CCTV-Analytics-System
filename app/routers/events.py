import logging
from typing import List

from fastapi import APIRouter, Request, Response
from pydantic import ValidationError

from app.database import get_db
from app.models import IngestRequest, IngestResponse, StoreEvent

logger = logging.getLogger("events")
router = APIRouter(tags=["Events"])


@router.post("/events/ingest", response_model=IngestResponse, status_code=207)
async def ingest_events(request: Request, response: Response, body: IngestRequest):
    """
    Ingest a batch of up to 500 store events.

    - **Idempotent**: duplicate event_ids are silently deduplicated.
    - **Partial success**: malformed rows return errors but valid rows are accepted.
    - Returns HTTP 207 Multi-Status with per-event outcomes.
    """
    db = await get_db()
    accepted = 0
    duplicate = 0
    errors: list = []

    for event in body.events:
        try:
            # Check duplicate
            async with db.execute(
                "SELECT 1 FROM events WHERE event_id = ?", (event.event_id,)
            ) as cur:
                row = await cur.fetchone()
            if row:
                duplicate += 1
                continue

            await db.execute(
                """
                INSERT INTO events (
                    event_id, store_id, camera_id, visitor_id, event_type,
                    timestamp, zone_id, dwell_ms, is_staff, confidence,
                    queue_depth, sku_zone, session_seq
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event.event_id,
                    event.store_id,
                    event.camera_id,
                    event.visitor_id,
                    event.event_type.value,
                    event.timestamp,
                    event.zone_id,
                    event.dwell_ms,
                    int(event.is_staff),
                    event.confidence,
                    event.metadata.queue_depth,
                    event.metadata.sku_zone,
                    event.metadata.session_seq,
                ),
            )
            accepted += 1

        except Exception as exc:
            errors.append({
                "event_id": event.event_id if hasattr(event, "event_id") else "unknown",
                "error": str(exc),
            })

    await db.commit()

    result = IngestResponse(
        accepted=accepted,
        rejected=len(errors),
        duplicate=duplicate,
        errors=errors,
    )

    # Surface event count in header for structured logging middleware
    response.headers["X-Event-Count"] = str(accepted)

    logger.info(
        "ingest_complete",
        extra={
            "accepted": accepted,
            "duplicate": duplicate,
            "rejected": len(errors),
        },
    )
    return result


@router.post("/events/ingest/pos", status_code=200)
async def ingest_pos_transactions(request: Request):
    """Ingest POS transaction records for conversion rate correlation."""
    body = await request.json()
    transactions = body.get("transactions", [])
    db = await get_db()
    inserted = 0
    for txn in transactions:
        try:
            await db.execute(
                """
                INSERT OR IGNORE INTO pos_transactions
                    (transaction_id, store_id, timestamp, basket_value_inr)
                VALUES (?, ?, ?, ?)
                """,
                (
                    txn["transaction_id"],
                    txn["store_id"],
                    txn["timestamp"],
                    float(txn["basket_value_inr"]),
                ),
            )
            inserted += 1
        except Exception:
            pass
    await db.commit()
    return {"inserted": inserted, "total": len(transactions)}
