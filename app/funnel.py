"""
funnel.py — Conversion funnel: Entry → Zone Visit → Billing Queue → Purchase.

Session is the unit. Re-entries do not double-count a visitor.
Stages and their drop-off percentages are computed from session-level flags.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.models import StoreFunnel, FunnelStage

logger = logging.getLogger("funnel")


async def compute_funnel(db, store_id: str, date: Optional[str]) -> StoreFunnel:
    date_str = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_prefix = f"{date_str}%"

    # Stage 1: unique customer sessions (de-duplicated by visitor_id)
    # Re-entries: same visitor_id only counted once per day
    async with db.execute(
        """
        SELECT COUNT(DISTINCT visitor_id) as cnt
        FROM events
        WHERE store_id=? AND is_staff=0 AND event_type='ENTRY'
          AND timestamp LIKE ?
        """,
        (store_id, date_prefix),
    ) as cur:
        row = await cur.fetchone()
    stage_entry = row["cnt"] if row else 0

    # Stage 2: visitors who visited at least one product zone
    async with db.execute(
        """
        SELECT COUNT(DISTINCT visitor_id) as cnt
        FROM events
        WHERE store_id=? AND is_staff=0
          AND event_type IN ('ZONE_ENTER','ZONE_DWELL')
          AND zone_id NOT IN ('BILLING','ENTRY_THRESHOLD')
          AND zone_id IS NOT NULL
          AND timestamp LIKE ?
        """,
        (store_id, date_prefix),
    ) as cur:
        row = await cur.fetchone()
    stage_zone = row["cnt"] if row else 0

    # Stage 3: visitors who entered billing zone
    async with db.execute(
        """
        SELECT COUNT(DISTINCT visitor_id) as cnt
        FROM events
        WHERE store_id=? AND is_staff=0
          AND zone_id='BILLING'
          AND event_type IN ('ZONE_ENTER','BILLING_QUEUE_JOIN')
          AND timestamp LIKE ?
        """,
        (store_id, date_prefix),
    ) as cur:
        row = await cur.fetchone()
    stage_billing = row["cnt"] if row else 0

    # Stage 4: visitors who completed purchase (POS-correlated, fall back to billing non-abandon)
    async with db.execute(
        "SELECT COUNT(*) as cnt FROM pos_transactions WHERE store_id=? AND timestamp LIKE ?",
        (store_id, date_prefix),
    ) as cur:
        row = await cur.fetchone()
    has_pos = (row["cnt"] or 0) > 0

    if has_pos:
        async with db.execute(
            """
            SELECT COUNT(DISTINCT e.visitor_id) as cnt
            FROM events e
            JOIN pos_transactions p
              ON p.store_id = e.store_id
             AND e.timestamp <= p.timestamp
             AND e.timestamp >= datetime(p.timestamp, '-5 minutes')
            WHERE e.store_id=? AND e.zone_id='BILLING' AND e.is_staff=0
              AND e.timestamp LIKE ?
            """,
            (store_id, date_prefix),
        ) as cur:
            row = await cur.fetchone()
        stage_purchase = row["cnt"] if row else 0
    else:
        # Estimate: billing visitors who did NOT abandon
        async with db.execute(
            """
            SELECT COUNT(DISTINCT visitor_id) as cnt
            FROM events
            WHERE store_id=? AND is_staff=0
              AND event_type='BILLING_QUEUE_ABANDON'
              AND timestamp LIKE ?
            """,
            (store_id, date_prefix),
        ) as cur:
            row = await cur.fetchone()
        abandons = row["cnt"] if row else 0
        stage_purchase = max(0, stage_billing - abandons)

    def drop_off(current: int, previous: int) -> float:
        if previous == 0:
            return 0.0
        return round((1 - current / previous) * 100, 1)

    stages = [
        FunnelStage(stage="Entry", count=stage_entry, drop_off_pct=0.0),
        FunnelStage(stage="Zone Visit", count=stage_zone, drop_off_pct=drop_off(stage_zone, stage_entry)),
        FunnelStage(stage="Billing Queue", count=stage_billing, drop_off_pct=drop_off(stage_billing, stage_zone)),
        FunnelStage(stage="Purchase", count=stage_purchase, drop_off_pct=drop_off(stage_purchase, stage_billing)),
    ]

    return StoreFunnel(
        store_id=store_id,
        date=date_str,
        stages=stages,
        sessions_analysed=stage_entry,
    )
