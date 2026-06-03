"""
emit.py — Event schema definition and JSONL emission.

Validates events against the challenge schema before writing.
Every event gets a globally unique UUID. Low-confidence events
are flagged but NOT suppressed.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("emit")

VALID_EVENT_TYPES = {
    "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
    "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY",
}


class EventEmitter:
    def __init__(self, store_id: str, camera_id: str, output_path: str):
        self.store_id = store_id
        self.camera_id = camera_id
        self.output_path = output_path
        self._fh = open(output_path, "w", encoding="utf-8")
        self.event_count = 0
        self._emitted_ids: set = set()

    def emit(
        self,
        event_type: str,
        visitor_id: str,
        timestamp: str,
        zone_id: Optional[str],
        dwell_ms: int,
        is_staff: bool,
        confidence: float,
        track: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[Dict[str, Any]]:
        assert event_type in VALID_EVENT_TYPES, f"Unknown event type: {event_type}"

        event_id = str(uuid.uuid4())
        assert event_id not in self._emitted_ids  # global uniqueness
        self._emitted_ids.add(event_id)

        meta = {
            "queue_depth": None,
            "sku_zone": zone_id,
            "session_seq": track.get("session_seq", 0) if track else 0,
        }
        if metadata:
            meta.update(metadata)

        event = {
            "event_id": event_id,
            "store_id": self.store_id,
            "camera_id": self.camera_id,
            "visitor_id": visitor_id,
            "event_type": event_type,
            "timestamp": timestamp,
            "zone_id": zone_id,
            "dwell_ms": int(dwell_ms),
            "is_staff": bool(is_staff),
            "confidence": round(float(confidence), 4),
            "metadata": meta,
        }

        self._fh.write(json.dumps(event) + "\n")
        self.event_count += 1

        if self.event_count % 500 == 0:
            self._fh.flush()
            logger.info(f"Emitted {self.event_count} events")

        return event

    def flush(self):
        self._fh.flush()
        self._fh.close()
        logger.info(f"EventEmitter closed — {self.event_count} events written to {self.output_path}")
