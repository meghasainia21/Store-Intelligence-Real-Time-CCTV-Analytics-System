
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class EventType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"


class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: int = 0

    class Config:
        extra = "allow"


class StoreEvent(BaseModel):
    event_id: str = Field(..., description="UUID-v4 globally unique")
    store_id: str = Field(..., min_length=1)
    camera_id: str = Field(..., min_length=1)
    visitor_id: str = Field(..., min_length=1)
    event_type: EventType
    timestamp: str = Field(..., description="ISO-8601 UTC")
    zone_id: Optional[str] = None
    dwell_ms: int = Field(..., ge=0)
    is_staff: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        # Accept ISO-8601 with or without Z
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"Invalid timestamp: {v}")
        return v

    @model_validator(mode="after")
    def validate_zone_rules(self) -> "StoreEvent":
        # ENTRY and EXIT must not have a zone_id
        if self.event_type in (EventType.ENTRY, EventType.EXIT, EventType.REENTRY):
            pass  # zone_id can be None
        # ZONE_* events should have a zone_id (warn but don't reject)
        return self


class IngestRequest(BaseModel):
    events: List[StoreEvent] = Field(..., max_length=500, min_length=1)


class IngestResponse(BaseModel):
    accepted: int
    rejected: int
    duplicate: int
    errors: List[Dict[str, Any]] = Field(default_factory=list)


# ── Analytics response models ──────────────────────────────────────────────

class ZoneDwell(BaseModel):
    zone_id: str
    avg_dwell_ms: float
    visit_count: int


class StoreMetrics(BaseModel):
    store_id: str
    date: str
    unique_visitors: int
    conversion_rate: float
    avg_basket_value_inr: Optional[float] = None
    avg_dwell_ms: float
    zone_dwells: List[ZoneDwell]
    queue_depth: int
    abandonment_rate: float
    total_entries: int
    total_exits: int
    staff_events_excluded: int


class FunnelStage(BaseModel):
    stage: str
    count: int
    drop_off_pct: float


class StoreFunnel(BaseModel):
    store_id: str
    date: str
    stages: List[FunnelStage]
    sessions_analysed: int


class ZoneHeatmapEntry(BaseModel):
    zone_id: str
    visit_frequency: int
    avg_dwell_ms: float
    normalised_score: float  # 0–100
    data_confidence: bool    # False if <20 sessions


class StoreHeatmap(BaseModel):
    store_id: str
    date: str
    zones: List[ZoneHeatmapEntry]


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class Anomaly(BaseModel):
    anomaly_id: str
    anomaly_type: str
    severity: Severity
    description: str
    suggested_action: str
    detected_at: str
    store_id: str
    zone_id: Optional[str] = None
    value: Optional[float] = None
    threshold: Optional[float] = None


class StoreAnomalies(BaseModel):
    store_id: str
    checked_at: str
    anomalies: List[Anomaly]


class StoreHealthStatus(BaseModel):
    store_id: str
    status: str  # OK | STALE_FEED | NO_DATA
    last_event_at: Optional[str]
    lag_minutes: Optional[float]


class HealthResponse(BaseModel):
    service: str
    status: str
    uptime_seconds: float
    stores: List[StoreHealthStatus]
    database: str
    checked_at: str
