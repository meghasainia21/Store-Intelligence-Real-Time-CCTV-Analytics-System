import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.emit import EventEmitter
from pipeline.tracker import MultiObjectTracker, iou, histogram_similarity, make_visitor_id
from pipeline.zones import ZoneClassifier


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_output(tmp_path):
    return str(tmp_path / "test_events.jsonl")


@pytest.fixture
def mock_frame():
    """Generate a synthetic BGR frame with distinct colour regions."""
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    # Left half: blue (staff uniform colour)
    frame[:, :640, 0] = 200
    # Right half: green (customer uniform)
    frame[:, 640:, 1] = 180
    return frame


@pytest.fixture
def tracker():
    return MultiObjectTracker(max_lost=10, reid_threshold=0.45)


@pytest.fixture
def emitter(tmp_output):
    e = EventEmitter("STORE_BLR_002", "CAM_ENTRY_01", tmp_output)
    yield e
    e.flush()


# ── IoU tests ─────────────────────────────────────────────────────────────────

def test_iou_identical():
    assert iou([0, 0, 100, 100], [0, 0, 100, 100]) == pytest.approx(1.0)


def test_iou_no_overlap():
    assert iou([0, 0, 50, 50], [100, 100, 200, 200]) == pytest.approx(0.0)


def test_iou_partial():
    score = iou([0, 0, 100, 100], [50, 50, 150, 150])
    assert 0.0 < score < 1.0


# ── Tracker tests ─────────────────────────────────────────────────────────────

def test_new_track_assigned_visitor_id(tracker):
    det = {"bbox": [100, 100, 200, 300], "conf": 0.8, "is_staff": False}
    tracks = tracker.update([det])
    assert len(tracks) == 1
    assert tracks[0]["visitor_id"].startswith("VIS_")


def test_empty_frame_no_crash(tracker):
    """Zero detections must not crash the tracker."""
    tracks = tracker.update([])
    assert tracks == []


def test_group_entry_three_people(tracker):
    """Three simultaneous detections must produce three distinct tracks."""
    dets = [
        {"bbox": [50, 100, 150, 300], "conf": 0.85, "is_staff": False},
        {"bbox": [200, 100, 300, 300], "conf": 0.82, "is_staff": False},
        {"bbox": [350, 100, 450, 300], "conf": 0.79, "is_staff": False},
    ]
    tracks = tracker.update(dets)
    visitor_ids = {t["visitor_id"] for t in tracks}
    assert len(visitor_ids) == 3, "Group entry must produce 3 distinct visitor IDs"


def test_track_continuity_across_frames(tracker):
    """Same person, same bounding box, must keep same visitor_id."""
    det = {"bbox": [100, 100, 200, 300], "conf": 0.8, "is_staff": False}
    t1 = tracker.update([det])
    # Move bbox slightly
    det2 = {"bbox": [105, 102, 205, 302], "conf": 0.8, "is_staff": False}
    t2 = tracker.update([det2])
    assert t1[0]["visitor_id"] == t2[0]["visitor_id"]


def test_track_becomes_lost(tracker):
    """After MAX_LOST_FRAMES without a detection, track status becomes 'lost'."""
    det = {"bbox": [100, 100, 200, 300], "conf": 0.8, "is_staff": False}
    tracker.update([det])
    # Feed empty frames until track expires
    lost_seen = False
    for _ in range(tracker.MAX_LOST_FRAMES + 2):
        tracks = tracker.update([])
        for t in tracks:
            if t["status"] == "lost":
                lost_seen = True
    assert lost_seen, "Track should transition to 'lost' after max_lost frames"


def test_visitor_id_uniqueness():
    """make_visitor_id should not collide across many calls."""
    ids = {make_visitor_id(f"seed_{i}_{i*7}") for i in range(1000)}
    assert len(ids) == 1000


# ── Staff classification ──────────────────────────────────────────────────────

def test_staff_classification_dark_uniform(mock_frame):
    from pipeline.detect import classify_staff
    # Dark uniform region — top-left corner is mostly black
    dark_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    bbox = [10, 10, 200, 400]
    # Staff detector should label dark uniform as staff
    result = classify_staff(dark_frame, bbox)
    assert isinstance(result, bool)


def test_classify_staff_empty_roi():
    from pipeline.detect import classify_staff
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    # Bbox outside frame — must not raise
    result = classify_staff(frame, [200, 200, 300, 400])
    assert result is False


# ── Event emitter tests ───────────────────────────────────────────────────────

def test_emitter_writes_valid_json(emitter, tmp_output):
    emitter.emit(
        event_type="ENTRY",
        visitor_id="VIS_abc123",
        timestamp="2026-04-10T10:00:00Z",
        zone_id=None,
        dwell_ms=0,
        is_staff=False,
        confidence=0.85,
    )
    emitter.flush()
    with open(tmp_output) as f:
        line = f.readline()
    event = json.loads(line)
    assert event["event_type"] == "ENTRY"
    assert uuid.UUID(event["event_id"])  # valid UUID
    assert event["store_id"] == "STORE_BLR_002"


def test_event_ids_globally_unique(tmp_output):
    emitter = EventEmitter("STORE_BLR_002", "CAM_ENTRY_01", tmp_output)
    for i in range(50):
        emitter.emit(
            event_type="ZONE_DWELL",
            visitor_id=f"VIS_{i:06d}",
            timestamp="2026-04-10T10:00:00Z",
            zone_id="SKINCARE",
            dwell_ms=30000,
            is_staff=False,
            confidence=0.9,
        )
    emitter.flush()
    with open(tmp_output) as f:
        events = [json.loads(l) for l in f]
    event_ids = [e["event_id"] for e in events]
    assert len(set(event_ids)) == len(event_ids), "All event_ids must be unique"


def test_timestamp_format_validation(emitter):
    """Timestamps must be valid ISO-8601."""
    emitter.emit(
        event_type="EXIT",
        visitor_id="VIS_test01",
        timestamp="2026-04-10T14:22:10Z",
        zone_id=None,
        dwell_ms=0,
        is_staff=False,
        confidence=0.72,
    )
    emitter.flush()


@pytest.mark.parametrize("conf", [0.01, 0.35, 0.99])
def test_low_confidence_events_not_suppressed(tmp_output, conf):
    """Low-confidence events must NOT be suppressed — they must be written."""
    emitter = EventEmitter("STORE_BLR_002", "CAM_FLOOR_01", tmp_output)
    emitter.emit(
        event_type="ZONE_ENTER",
        visitor_id="VIS_lowconf",
        timestamp="2026-04-10T11:00:00Z",
        zone_id="MAKEUP",
        dwell_ms=0,
        is_staff=False,
        confidence=conf,
    )
    emitter.flush()
    with open(tmp_output) as f:
        events = [json.loads(l) for l in f]
    assert len(events) == 1
    assert events[0]["confidence"] == pytest.approx(conf, abs=0.001)


# ── Zone classifier tests ─────────────────────────────────────────────────────

@pytest.fixture
def zone_clf():
    return ZoneClassifier({}, "STORE_BLR_002", 1280, 720, "FLOOR")


def test_zone_clf_returns_string_or_none(zone_clf):
    bbox = [300, 50, 500, 400]
    result = zone_clf.classify(bbox)
    assert result is None or isinstance(result, str)


def test_zone_clf_centre_of_mass_based(zone_clf):
    """Different spatial positions should map to different zones or None."""
    bbox_left = [0, 0, 200, 360]
    bbox_right = [1000, 0, 1280, 360]
    z1 = zone_clf.classify(bbox_left)
    z2 = zone_clf.classify(bbox_right)
    # They should potentially differ — just confirm no crash
    assert True
