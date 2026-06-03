"""
routers/stores.py — All /stores/{id}/* analytics endpoints.

Endpoints:
  GET /stores/{id}/metrics   — real-time KPIs
  GET /stores/{id}/funnel    — conversion funnel
  GET /stores/{id}/heatmap   — zone dwell heatmap
  GET /stores/{id}/anomalies — active anomalies
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.database import get_db
from app.metrics import compute_metrics
from app.funnel import compute_funnel
from app.heatmap import compute_heatmap
from app.anomalies import detect_anomalies
from app.models import StoreMetrics, StoreFunnel, StoreHeatmap, StoreAnomalies

logger = logging.getLogger("stores")
router = APIRouter(prefix="/stores", tags=["Stores"])


@router.get("/{store_id}/metrics", response_model=StoreMetrics)
async def get_metrics(
    store_id: str,
    date: Optional[str] = Query(None, description="Date filter YYYY-MM-DD (default: today)"),
):
    """
    Real-time store KPIs.

    - Excludes is_staff=True events from all customer metrics.
    - Handles zero-purchase stores without division errors.
    - Conversion rate: visitors in billing window before a POS transaction ÷ total unique visitors.
    """
    db = await get_db()
    return await compute_metrics(db, store_id, date)


@router.get("/{store_id}/funnel", response_model=StoreFunnel)
async def get_funnel(
    store_id: str,
    date: Optional[str] = Query(None),
):
    """
    Conversion funnel: Entry → Zone Visit → Billing Queue → Purchase.

    - Session is the unit of analysis, not raw events.
    - Re-entries do not double-count a visitor within the same day.
    - Drop-off % is relative to the previous stage.
    """
    db = await get_db()
    return await compute_funnel(db, store_id, date)


@router.get("/{store_id}/heatmap", response_model=StoreHeatmap)
async def get_heatmap(
    store_id: str,
    date: Optional[str] = Query(None),
):
    """
    Zone visit frequency + avg dwell, normalised 0–100.

    - data_confidence = False when fewer than 20 sessions in window.
    - Ready for grid heatmap rendering — scores are 0–100.
    """
    db = await get_db()
    return await compute_heatmap(db, store_id, date)


@router.get("/{store_id}/anomalies", response_model=StoreAnomalies)
async def get_anomalies(
    store_id: str,
):
    """
    Active operational anomalies.

    Types: QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE, HIGH_ABANDONMENT.
    Severity: INFO / WARN / CRITICAL.
    Each anomaly includes a suggested_action string.
    """
    db = await get_db()
    return await detect_anomalies(db, store_id)
