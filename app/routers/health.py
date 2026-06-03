"""
routers/health.py — GET /health

Returns service status, DB status, and per-store feed freshness.
STALE_FEED is raised if any store's last event is >10 minutes old.
This is the endpoint an on-call engineer checks first.
"""

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter

from app.database import get_db, check_db_health
from app.models import HealthResponse, StoreHealthStatus

logger = logging.getLogger("health")
router = APIRouter(tags=["Health"])

_start_time = time.time()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Service health check.

    Returns STALE_FEED per store if last event > 10 minutes ago.
    Database connectivity is checked independently.
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db_ok = await check_db_health()
    db_status = "ok" if db_ok else "unavailable"

    store_statuses = []
    if db_ok:
        try:
            db = await get_db()
            async with db.execute(
                """
                SELECT store_id, MAX(timestamp) as last_event
                FROM events
                GROUP BY store_id
                """
            ) as cur:
                rows = await cur.fetchall()

            now_dt = datetime.now(timezone.utc)
            for row in rows:
                sid = row["store_id"]
                last_event_str = row["last_event"]
                try:
                    last_event_dt = datetime.fromisoformat(
                        last_event_str.replace("Z", "+00:00")
                    )
                    lag_minutes = (now_dt - last_event_dt).total_seconds() / 60
                    if lag_minutes > 10:
                        status = "STALE_FEED"
                    else:
                        status = "OK"
                except Exception:
                    lag_minutes = None
                    status = "UNKNOWN"

                store_statuses.append(
                    StoreHealthStatus(
                        store_id=sid,
                        status=status,
                        last_event_at=last_event_str,
                        lag_minutes=round(lag_minutes, 1) if lag_minutes is not None else None,
                    )
                )
        except Exception as e:
            logger.error(f"Health check DB query failed: {e}")

    if not store_statuses:
        store_statuses.append(
            StoreHealthStatus(
                store_id="NO_STORES",
                status="NO_DATA",
                last_event_at=None,
                lag_minutes=None,
            )
        )

    overall = "ok" if db_ok else "degraded"

    return HealthResponse(
        service="store-intelligence-api",
        status=overall,
        uptime_seconds=round(time.time() - _start_time, 1),
        stores=store_statuses,
        database=db_status,
        checked_at=now_iso,
    )
