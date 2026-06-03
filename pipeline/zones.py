

from __future__ import annotations

import json
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger("zones")


DEFAULT_ZONES = {
    "STORE_BLR_002": {
        "store_id": "STORE_BLR_002",
        "open_hours": {"open": "10:00", "close": "22:00"},
        "cameras": {
            "CAM_ENTRY_01": {
                "type": "ENTRY",
                "zones": [
                    {"zone_id": "ENTRY_THRESHOLD", "bbox_norm": [0.0, 0.7, 1.0, 1.0]},
                    {"zone_id": "FRAGRANCE", "bbox_norm": [0.0, 0.3, 0.5, 0.7]},
                    {"zone_id": "SKINCARE", "bbox_norm": [0.5, 0.3, 1.0, 0.7]},
                ]
            },
            "CAM_FLOOR_01": {
                "type": "FLOOR",
                "zones": [
                    {"zone_id": "SKINCARE", "bbox_norm": [0.0, 0.0, 0.33, 0.5]},
                    {"zone_id": "MAKEUP", "bbox_norm": [0.33, 0.0, 0.66, 0.5]},
                    {"zone_id": "HAIRCARE", "bbox_norm": [0.66, 0.0, 1.0, 0.5]},
                    {"zone_id": "FRAGRANCE", "bbox_norm": [0.0, 0.5, 0.33, 1.0]},
                    {"zone_id": "BODYCARE", "bbox_norm": [0.33, 0.5, 0.66, 1.0]},
                    {"zone_id": "NAILCARE", "bbox_norm": [0.66, 0.5, 1.0, 1.0]},
                ]
            },
            "CAM_BILLING_01": {
                "type": "BILLING",
                "zones": [
                    {"zone_id": "BILLING", "bbox_norm": [0.0, 0.0, 1.0, 1.0]},
                ]
            }
        }
    }
}


class ZoneClassifier:
    """
    Classifies bounding boxes into store zones.

    Zone assignment uses the centre-of-mass of the bounding box
    (more stable than full overlap for tall person detections).
    """

    def __init__(
        self,
        layout: dict,
        store_id: str,
        frame_w: int,
        frame_h: int,
        camera_type: str,
    ):
        self.store_id = store_id
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.camera_type = camera_type
        self.zones = self._load_zones(layout, store_id, camera_type)
        logger.info(f"ZoneClassifier: {len(self.zones)} zones loaded for {store_id}/{camera_type}")

    def _load_zones(self, layout: dict, store_id: str, camera_type: str) -> list:
        """Load zones from layout JSON or fall back to defaults."""
        # Try real layout
        if layout and "stores" in layout:
            for store in layout.get("stores", []):
                if store.get("store_id") == store_id:
                    for cam in store.get("cameras", []):
                        if cam.get("type") == camera_type:
                            return cam.get("zones", [])

        # Fallback to default zones for this store
        store_layout = DEFAULT_ZONES.get(store_id, DEFAULT_ZONES.get("STORE_BLR_002", {}))
        cameras = store_layout.get("cameras", {})
        for cam_id, cam_data in cameras.items():
            if cam_data.get("type") == camera_type:
                return cam_data.get("zones", [])
        return []

    def classify(self, bbox: list) -> Optional[str]:
        """Return zone_id for the centre of a bounding box, or None."""
        cx = (bbox[0] + bbox[2]) / 2 / self.frame_w
        # Use bottom-third of bbox as foot position (more accurate for zone)
        cy = (bbox[1] * 0.3 + bbox[3] * 0.7) / self.frame_h

        for zone in self.zones:
            norm = zone.get("bbox_norm", [])
            if len(norm) != 4:
                continue
            x1n, y1n, x2n, y2n = norm
            if x1n <= cx <= x2n and y1n <= cy <= y2n:
                return zone["zone_id"]
        return None


def get_store_open_hours(layout: dict, store_id: str) -> dict:
    """Return {"open": "HH:MM", "close": "HH:MM"} for the store."""
    if layout and "stores" in layout:
        for store in layout.get("stores", []):
            if store.get("store_id") == store_id:
                return store.get("open_hours", {"open": "10:00", "close": "22:00"})
    store_layout = DEFAULT_ZONES.get(store_id, DEFAULT_ZONES.get("STORE_BLR_002", {}))
    return store_layout.get("open_hours", {"open": "10:00", "close": "22:00"})
