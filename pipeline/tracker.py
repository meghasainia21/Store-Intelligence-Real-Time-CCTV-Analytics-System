
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


def iou(boxA: list, boxB: list) -> float:
    """Intersection over Union for two bounding boxes [x1,y1,x2,y2]."""
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    inter = max(0, xB - xA) * max(0, yB - yA)
    if inter == 0:
        return 0.0
    aA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    aB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    return inter / float(aA + aB - inter)


def extract_histogram(frame: np.ndarray, bbox: list, bins: int = 32) -> Optional[np.ndarray]:
    """Extract HSV colour histogram for appearance matching."""
    x1, y1, x2, y2 = [int(v) for v in bbox]
    roi = frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
    if roi.size == 0 or roi.shape[0] < 10 or roi.shape[1] < 10:
        return None
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    hist_h = cv2.calcHist([hsv], [0], None, [bins], [0, 180])
    hist_s = cv2.calcHist([hsv], [1], None, [bins], [0, 256])
    hist = np.concatenate([hist_h, hist_s])
    cv2.normalize(hist, hist)
    return hist.flatten()


def histogram_similarity(h1: np.ndarray, h2: np.ndarray) -> float:
    """Bhattacharyya-based similarity, 1.0 = identical."""
    dist = cv2.compareHist(h1.reshape(-1, 1), h2.reshape(-1, 1), cv2.HISTCMP_BHATTACHARYYA)
    return 1.0 - float(dist)


def make_visitor_id(seed: str) -> str:
    """Generate a deterministic short visitor ID from a seed string."""
    h = hashlib.sha256(seed.encode()).hexdigest()[:6]
    return f"VIS_{h}"


@dataclass
class Track:
    track_id: int
    visitor_id: str
    bbox: list
    conf: float
    is_staff: bool
    histogram: Optional[np.ndarray]
    age: int = 0                   # frames seen
    lost_age: int = 0              # frames since last match
    dwell_ms: float = 0.0
    session_seq: int = 0
    zone_history: list = field(default_factory=list)
    status: str = "new"            # new | active | lost | reentry
    created_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    exited: bool = False


class MultiObjectTracker:
    """
    IoU + appearance-based tracker.

    Matching strategy (priority order):
      1. High IoU (>0.5) — same frame spatial match
      2. Appearance similarity — handles occlusion + re-entry
    """

    IOU_THRESHOLD = 0.35
    APPEARANCE_THRESHOLD = 0.55   # min similarity to consider a match
    MAX_LOST_FRAMES = 45          # ~3s at 15fps sampled every 1 frame
    REENTRY_WINDOW_SEC = 180.0    # how long to remember exited visitors
    MIN_TRACK_AGE = 2             # discard phantom 1-frame detections

    def __init__(self, max_lost: int = 45, reid_threshold: float = 0.45):
        self.MAX_LOST_FRAMES = max_lost
        self.APPEARANCE_THRESHOLD = reid_threshold
        self._next_id: int = 1
        self._active_tracks: Dict[int, Track] = {}
        self._exited_tracks: List[Track] = []   # ring buffer for re-ID
        self._frame: Optional[np.ndarray] = None
        self._frame_ms_per_sample: float = 1000.0 / 5  # assume 5fps sampling
        self._billing_zone_tracks: set = set()

    def _new_track(self, det: dict) -> Track:
        tid = self._next_id
        self._next_id += 1
        vid = make_visitor_id(f"{tid}_{time.time()}")
        hist = extract_histogram(self._frame, det["bbox"]) if self._frame is not None else None
        return Track(
            track_id=tid,
            visitor_id=vid,
            bbox=det["bbox"],
            conf=det["conf"],
            is_staff=det.get("is_staff", False),
            histogram=hist,
            status="new",
        )

    def _match_detections(self, detections: list) -> Tuple[dict, list, list]:
        """
        Returns:
          matched: {track_id: det_index}
          unmatched_tracks: [track_id]
          unmatched_dets: [det_index]
        """
        if not self._active_tracks or not detections:
            return {}, list(self._active_tracks.keys()), list(range(len(detections)))

        tids = list(self._active_tracks.keys())
        n_t, n_d = len(tids), len(detections)

        # Build IoU matrix
        iou_mat = np.zeros((n_t, n_d))
        for i, tid in enumerate(tids):
            for j, det in enumerate(detections):
                iou_mat[i, j] = iou(self._active_tracks[tid].bbox, det["bbox"])

        matched = {}
        matched_t, matched_d = set(), set()

        # Greedy match on highest IoU first
        flat_indices = np.argsort(-iou_mat, axis=None)
        for flat_idx in flat_indices:
            i, j = divmod(flat_idx, n_d)
            if iou_mat[i, j] < self.IOU_THRESHOLD:
                break
            if i in matched_t or j in matched_d:
                continue
            matched[tids[i]] = j
            matched_t.add(i)
            matched_d.add(j)

        # Appearance-based second pass for unmatched
        if self._frame is not None:
            for i, tid in enumerate(tids):
                if i in matched_t:
                    continue
                track = self._active_tracks[tid]
                if track.histogram is None:
                    continue
                best_sim, best_j = 0.0, -1
                for j, det in enumerate(detections):
                    if j in matched_d:
                        continue
                    det_hist = extract_histogram(self._frame, det["bbox"])
                    if det_hist is None:
                        continue
                    sim = histogram_similarity(track.histogram, det_hist)
                    if sim > best_sim:
                        best_sim, best_j = sim, j
                if best_sim >= self.APPEARANCE_THRESHOLD and best_j >= 0:
                    matched[tid] = best_j
                    matched_t.add(i)
                    matched_d.add(best_j)

        unmatched_t = [tids[i] for i in range(n_t) if i not in matched_t]
        unmatched_d = [j for j in range(n_d) if j not in matched_d]
        return matched, unmatched_t, unmatched_d

    def _try_reentry(self, det: dict) -> Optional[Track]:
        """Check if an unmatched detection matches a recently-exited visitor."""
        if not self._exited_tracks:
            return None
        det_hist = extract_histogram(self._frame, det["bbox"]) if self._frame is not None else None
        if det_hist is None:
            return None
        now = time.time()
        best_sim, best_track = 0.0, None
        for t in self._exited_tracks:
            if now - t.last_seen_at > self.REENTRY_WINDOW_SEC:
                continue
            if t.histogram is None:
                continue
            sim = histogram_similarity(t.histogram, det_hist)
            if sim > best_sim:
                best_sim, best_track = sim, t
        if best_sim >= self.APPEARANCE_THRESHOLD + 0.1 and best_track is not None:
            return best_track
        return None

    def update(self, detections: list, frame: np.ndarray = None) -> list:
        """
        Update tracker with a new set of detections.
        Returns list of track dicts with status field.
        """
        self._frame = frame
        self._frame_ms_per_sample = self._frame_ms_per_sample  # retain

        matched, unmatched_t, unmatched_d = self._match_detections(detections)

        output_tracks = []

        # Update matched tracks
        for tid, det_idx in matched.items():
            det = detections[det_idx]
            track = self._active_tracks[tid]
            track.bbox = det["bbox"]
            track.conf = det["conf"]
            track.is_staff = det.get("is_staff", track.is_staff)
            track.age += 1
            track.lost_age = 0
            track.dwell_ms += self._frame_ms_per_sample
            track.session_seq += 1
            track.last_seen_at = time.time()
            if self._frame is not None:
                new_hist = extract_histogram(self._frame, track.bbox)
                if new_hist is not None:
                    if track.histogram is not None:
                        # Exponential moving average for histogram smoothing
                        track.histogram = 0.7 * track.histogram + 0.3 * new_hist
                    else:
                        track.histogram = new_hist
            prev_status = track.status
            track.status = "active" if prev_status != "new" else "new"
            if track.age >= self.MIN_TRACK_AGE:
                output_tracks.append(self._track_to_dict(track))

        # Handle lost tracks
        lost_to_remove = []
        for tid in unmatched_t:
            track = self._active_tracks[tid]
            track.lost_age += 1
            if track.lost_age >= self.MAX_LOST_FRAMES:
                track.status = "lost"
                track.exited = True
                if track.age >= self.MIN_TRACK_AGE:
                    output_tracks.append(self._track_to_dict(track))
                self._exited_tracks.append(track)
                # Prune old exited tracks
                now = time.time()
                self._exited_tracks = [
                    t for t in self._exited_tracks
                    if now - t.last_seen_at <= self.REENTRY_WINDOW_SEC
                ]
                lost_to_remove.append(tid)

        for tid in lost_to_remove:
            del self._active_tracks[tid]

        # Handle new detections
        for det_idx in unmatched_d:
            det = detections[det_idx]
            reentry_track = self._try_reentry(det)
            if reentry_track is not None:
                # Re-use existing visitor_id; flag as re-entry
                reentry_track.exited = False
                reentry_track.lost_age = 0
                reentry_track.age += 1
                reentry_track.session_seq += 1
                reentry_track.bbox = det["bbox"]
                reentry_track.conf = det["conf"]
                reentry_track.status = "reentry"
                reentry_track.last_seen_at = time.time()
                self._active_tracks[reentry_track.track_id] = reentry_track
                self._exited_tracks = [
                    t for t in self._exited_tracks if t.track_id != reentry_track.track_id
                ]
                output_tracks.append(self._track_to_dict(reentry_track))
            else:
                track = self._new_track(det)
                self._active_tracks[track.track_id] = track
                output_tracks.append(self._track_to_dict(track))

        return output_tracks

    def _track_to_dict(self, track: Track) -> dict:
        return {
            "track_id": track.track_id,
            "visitor_id": track.visitor_id,
            "bbox": track.bbox,
            "conf": round(track.conf, 4),
            "is_staff": track.is_staff,
            "dwell_ms": int(track.dwell_ms),
            "session_seq": track.session_seq,
            "status": track.status,
            "age": track.age,
        }

    def get_billing_queue_depth(self) -> int:
        """Return count of non-staff active tracks currently in billing zone."""
        return len(self._billing_zone_tracks)

    def mark_in_billing(self, visitor_id: str):
        self._billing_zone_tracks.add(visitor_id)

    def unmark_billing(self, visitor_id: str):
        self._billing_zone_tracks.discard(visitor_id)
