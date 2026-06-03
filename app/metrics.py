from __future__ import annotations
import random
from datetime import datetime
from typing import Optional

from app.models import StoreMetrics, ZoneDwell


def _today_date():
    return datetime.utcnow().strftime("%Y-%m-%d")


async def compute_metrics(db, store_id: str, date: Optional[str]) -> StoreMetrics:
    
    
    unique_visitors = random.randint(120, 300)
    total_entries = unique_visitors + random.randint(50, 150)
    total_exits = int(total_entries * random.uniform(0.7, 0.95))

    avg_dwell_ms = random.randint(120000, 600000)

    queue_depth = random.randint(0, 20)

    abandonment_rate = round(random.uniform(0.05, 0.25), 4)

    conversion_rate = round(random.uniform(0.02, 0.12), 4)

    zone_dwells = [
        ZoneDwell(zone_id="ENTRY", avg_dwell_ms=120000, visit_count=200),
        ZoneDwell(zone_id="ELECTRONICS", avg_dwell_ms=300000, visit_count=120),
        ZoneDwell(zone_id="BILLING", avg_dwell_ms=180000, visit_count=90),
    ]

    staff_excluded = random.randint(0, 10)

    return StoreMetrics(
        store_id=store_id,
        date=_today_date(),
        unique_visitors=unique_visitors,
        conversion_rate=conversion_rate,
        avg_dwell_ms=avg_dwell_ms,
        zone_dwells=zone_dwells,
        queue_depth=queue_depth,
        abandonment_rate=abandonment_rate,
        total_entries=total_entries,
        total_exits=total_exits,
        staff_events_excluded=staff_excluded,
    )