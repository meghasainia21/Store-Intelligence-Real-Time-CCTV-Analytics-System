"""
heatmap.py — Zone dwell frequency heatmap, normalised 0–100.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.models import StoreHeatmap, ZoneHeatmapEntry

logger = logging.getLogger("heatmap")

MIN_SESSIONS_FOR_CONFIDENCE = 20


async def compute_heatmap(db, store_id: str, date: Optional[str]) -> StoreHeatmap:
    date_str = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_prefix = f"{date_str}%"

    # Total unique sessions
    async with db.execute(
        """
        SELECT COUNT(DISTINCT visitor_id) as cnt
        FROM events WHERE store_id=? AND is_staff=0
          AND event_type='ENTRY' AND timestamp LIKE ?
        """,
        (store_id, date_prefix),
    ) as cur:
        row = await cur.fetchone()
    total_sessions = row["cnt"] if row else 0
    has_confidence = total_sessions >= MIN_SESSIONS_FOR_CONFIDENCE

    async with db.execute(
        """
        SELECT zone_id,
               COUNT(*) as visit_count,
               AVG(dwell_ms) as avg_dwell
        FROM events
        WHERE store_id=? AND is_staff=0 AND zone_id IS NOT NULL
          AND dwell_ms > 0
          AND event_type IN ('ZONE_DWELL','ZONE_EXIT')
          AND timestamp LIKE ?
        GROUP BY zone_id
        ORDER BY avg_dwell DESC
        """,
        (store_id, date_prefix),
    ) as cur:
        rows = await cur.fetchall()

    if not rows:
        return StoreHeatmap(store_id=store_id, date=date_str, zones=[])

    max_dwell = max(r["avg_dwell"] for r in rows) or 1.0

    zones = [
        ZoneHeatmapEntry(
            zone_id=r["zone_id"],
            visit_frequency=r["visit_count"],
            avg_dwell_ms=round(float(r["avg_dwell"]), 1),
            normalised_score=round((r["avg_dwell"] / max_dwell) * 100, 1),
            data_confidence=has_confidence,
        )
        for r in rows
    ]

    return StoreHeatmap(store_id=store_id, date=date_str, zones=zones)
