from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import List

from app.models import Anomaly, Severity, StoreAnomalies

logger = logging.getLogger("anomalies")

QUEUE_SPIKE_WARN = 3
QUEUE_SPIKE_CRITICAL = 6
ABANDONMENT_WARN = 0.30
ABANDONMENT_CRITICAL = 0.50
CONVERSION_DROP_WARN_PCT = 0.25      # 25% below 7-day avg
CONVERSION_DROP_CRITICAL_PCT = 0.50
DEAD_ZONE_MINUTES = 30


async def detect_anomalies(db, store_id: str) -> StoreAnomalies:
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    today_prefix = f"{now.strftime('%Y-%m-%d')}%"
    anomalies: List[Anomaly] = []

    # ── 1. Queue spike ──────────────────────────────────────────────────
    async with db.execute(
        """
        SELECT COUNT(DISTINCT visitor_id) as depth
        FROM events
        WHERE store_id=? AND zone_id='BILLING' AND is_staff=0
          AND event_type='BILLING_QUEUE_JOIN' AND timestamp LIKE ?
        """,
        (store_id, today_prefix),
    ) as cur:
        row = await cur.fetchone()
    queue_depth = row["depth"] if row else 0

    if queue_depth >= QUEUE_SPIKE_CRITICAL:
        anomalies.append(Anomaly(
            anomaly_id=str(uuid.uuid4()),
            anomaly_type="BILLING_QUEUE_SPIKE",
            severity=Severity.CRITICAL,
            description=f"Billing queue depth is {queue_depth} — critically high. Customer wait times may be exceeding tolerance.",
            suggested_action="Open additional billing counters immediately. Consider calling floor staff to assist at POS.",
            detected_at=now_iso,
            store_id=store_id,
            zone_id="BILLING",
            value=float(queue_depth),
            threshold=float(QUEUE_SPIKE_CRITICAL),
        ))
    elif queue_depth >= QUEUE_SPIKE_WARN:
        anomalies.append(Anomaly(
            anomaly_id=str(uuid.uuid4()),
            anomaly_type="BILLING_QUEUE_SPIKE",
            severity=Severity.WARN,
            description=f"Billing queue at {queue_depth}. Growing — monitor closely.",
            suggested_action="Alert floor manager. Prepare to redirect a staff member to billing.",
            detected_at=now_iso,
            store_id=store_id,
            zone_id="BILLING",
            value=float(queue_depth),
            threshold=float(QUEUE_SPIKE_WARN),
        ))

    # ── 2. Conversion drop vs 7-day rolling average ──────────────────────
    today_str = now.strftime("%Y-%m-%d")

    async with db.execute(
        """
        SELECT COUNT(DISTINCT visitor_id) as visitors
        FROM events
        WHERE store_id=? AND is_staff=0 AND event_type='ENTRY'
          AND timestamp LIKE ?
        """,
        (store_id, today_prefix),
    ) as cur:
        row = await cur.fetchone()
    today_visitors = row["visitors"] if row else 0

    async with db.execute(
        """
        SELECT COUNT(DISTINCT visitor_id) as converted
        FROM events
        WHERE store_id=? AND is_staff=0 AND zone_id='BILLING'
          AND event_type IN ('ZONE_ENTER','BILLING_QUEUE_JOIN')
          AND timestamp LIKE ?
        """,
        (store_id, today_prefix),
    ) as cur:
        row = await cur.fetchone()
    today_converted = row["converted"] if row else 0
    today_conv = today_converted / today_visitors if today_visitors > 0 else None

    # 7-day historical average (excluding today)
    past_7_days = [
        (now - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(1, 8)
    ]
    hist_convs = []
    for d in past_7_days:
        async with db.execute(
            """
            SELECT COUNT(DISTINCT visitor_id) as v
            FROM events WHERE store_id=? AND is_staff=0 AND event_type='ENTRY'
            AND timestamp LIKE ?
            """,
            (store_id, f"{d}%"),
        ) as cur:
            vrow = await cur.fetchone()
        async with db.execute(
            """
            SELECT COUNT(DISTINCT visitor_id) as c
            FROM events WHERE store_id=? AND is_staff=0 AND zone_id='BILLING'
            AND event_type IN ('ZONE_ENTER','BILLING_QUEUE_JOIN') AND timestamp LIKE ?
            """,
            (store_id, f"{d}%"),
        ) as cur:
            crow = await cur.fetchone()
        v = vrow["v"] if vrow else 0
        c = crow["c"] if crow else 0
        if v > 0:
            hist_convs.append(c / v)

    if hist_convs and today_conv is not None:
        avg_hist = sum(hist_convs) / len(hist_convs)
        if avg_hist > 0:
            drop_pct = (avg_hist - today_conv) / avg_hist
            if drop_pct >= CONVERSION_DROP_CRITICAL_PCT:
                anomalies.append(Anomaly(
                    anomaly_id=str(uuid.uuid4()),
                    anomaly_type="CONVERSION_DROP",
                    severity=Severity.CRITICAL,
                    description=(
                        f"Today's conversion ({today_conv:.1%}) is {drop_pct:.0%} below "
                        f"the 7-day average ({avg_hist:.1%}). Significant revenue at risk."
                    ),
                    suggested_action="Review today's promotions and staff activity. Check for product availability issues in high-dwell zones.",
                    detected_at=now_iso,
                    store_id=store_id,
                    value=round(today_conv, 4),
                    threshold=round(avg_hist, 4),
                ))
            elif drop_pct >= CONVERSION_DROP_WARN_PCT:
                anomalies.append(Anomaly(
                    anomaly_id=str(uuid.uuid4()),
                    anomaly_type="CONVERSION_DROP",
                    severity=Severity.WARN,
                    description=(
                        f"Today's conversion ({today_conv:.1%}) is {drop_pct:.0%} below "
                        f"the 7-day average ({avg_hist:.1%})."
                    ),
                    suggested_action="Monitor closely. Consider activating a promotion or deploying a floor staff member to assist customers.",
                    detected_at=now_iso,
                    store_id=store_id,
                    value=round(today_conv, 4),
                    threshold=round(avg_hist, 4),
                ))

    # ── 3. Dead zones (no visits in past 30 min) ─────────────────────────
    cutoff = (now - timedelta(minutes=DEAD_ZONE_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with db.execute(
        """
        SELECT DISTINCT zone_id FROM events
        WHERE store_id=? AND is_staff=0 AND zone_id IS NOT NULL
          AND zone_id != 'BILLING' AND timestamp >= ?
        """,
        (store_id, cutoff),
    ) as cur:
        active_zones = {r["zone_id"] for r in await cur.fetchall()}

    # All zones seen today
    async with db.execute(
        """
        SELECT DISTINCT zone_id FROM events
        WHERE store_id=? AND zone_id IS NOT NULL
          AND zone_id != 'BILLING' AND timestamp LIKE ?
        """,
        (store_id, today_prefix),
    ) as cur:
        all_zones = {r["zone_id"] for r in await cur.fetchall()}

    dead_zones = all_zones - active_zones
    for zone_id in dead_zones:
        anomalies.append(Anomaly(
            anomaly_id=str(uuid.uuid4()),
            anomaly_type="DEAD_ZONE",
            severity=Severity.INFO,
            description=f"Zone '{zone_id}' has had no customer visits in the past {DEAD_ZONE_MINUTES} minutes.",
            suggested_action=f"Check product display and signage in {zone_id}. Consider moving a promotional display to attract traffic.",
            detected_at=now_iso,
            store_id=store_id,
            zone_id=zone_id,
            value=float(DEAD_ZONE_MINUTES),
            threshold=float(DEAD_ZONE_MINUTES),
        ))

    # ── 4. High abandonment ──────────────────────────────────────────────
    async with db.execute(
        """
        SELECT
          SUM(CASE WHEN event_type='BILLING_QUEUE_JOIN' THEN 1 ELSE 0 END) as joins,
          SUM(CASE WHEN event_type='BILLING_QUEUE_ABANDON' THEN 1 ELSE 0 END) as abandons
        FROM events WHERE store_id=? AND is_staff=0 AND timestamp LIKE ?
        """,
        (store_id, today_prefix),
    ) as cur:
        row = await cur.fetchone()
    joins = row["joins"] or 0
    abandons = row["abandons"] or 0
    abandon_rate = abandons / joins if joins > 0 else 0.0

    if abandon_rate >= ABANDONMENT_CRITICAL:
        anomalies.append(Anomaly(
            anomaly_id=str(uuid.uuid4()),
            anomaly_type="HIGH_ABANDONMENT",
            severity=Severity.CRITICAL,
            description=f"Queue abandonment rate is {abandon_rate:.0%} — customers are leaving before purchase.",
            suggested_action="Escalate to store manager. Open more billing counters. Consider express checkout for small baskets.",
            detected_at=now_iso,
            store_id=store_id,
            zone_id="BILLING",
            value=round(abandon_rate, 4),
            threshold=ABANDONMENT_CRITICAL,
        ))
    elif abandon_rate >= ABANDONMENT_WARN:
        anomalies.append(Anomaly(
            anomaly_id=str(uuid.uuid4()),
            anomaly_type="HIGH_ABANDONMENT",
            severity=Severity.WARN,
            description=f"Queue abandonment rate is {abandon_rate:.0%}.",
            suggested_action="Speed up billing process. Engage customers waiting in queue with product sampling.",
            detected_at=now_iso,
            store_id=store_id,
            zone_id="BILLING",
            value=round(abandon_rate, 4),
            threshold=ABANDONMENT_WARN,
        ))

    return StoreAnomalies(
        store_id=store_id,
        checked_at=now_iso,
        anomalies=anomalies,
    )
