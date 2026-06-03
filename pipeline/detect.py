import argparse
import json
import logging
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import cv2
import numpy as np

from tracker import MultiObjectTracker
from emit import EventEmitter
from zones import ZoneClassifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("detect")


def parse_args():
    p = argparse.ArgumentParser(description="Store CCTV Detection Pipeline")
    p.add_argument("--video", required=True, help="Path to input video clip")
    p.add_argument("--store-id", required=True, help="Store ID (e.g. STORE_BLR_002)")
    p.add_argument("--camera-id", required=True, help="Camera ID (e.g. CAM_ENTRY_01)")
    p.add_argument("--layout", default="store_layout.json", help="Zone layout JSON")
    p.add_argument("--output", default="events.jsonl", help="Output events file")
    p.add_argument("--clip-start", default=None, help="Clip start time ISO-8601 UTC")
    p.add_argument("--conf-threshold", type=float, default=0.35, help="Detection confidence threshold")
    p.add_argument("--device", default="cpu", help="Inference device: cpu or cuda")
    p.add_argument("--batch-size", type=int, default=1)
    p.add_argument("--fps-sample", type=int, default=5, help="Process every N frames")
    return p.parse_args()


def load_layout(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def frame_to_timestamp(clip_start: datetime, frame_idx: int, fps: float) -> str:
    offset_sec = frame_idx / fps
    ts = clip_start + timedelta(seconds=offset_sec)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_yolo_model(device: str):
    
    try:
        from ultralytics import YOLO  # type: ignore
        model = YOLO("yolov8n.pt")
        model.to(device)
        logger.info("Loaded YOLOv8n from ultralytics")
        return model, "ultralytics"
    except ImportError:
        logger.warning("ultralytics not installed — using mock detection model")
        return None, "mock"


def detect_persons_ultralytics(model, frame: np.ndarray, conf_threshold: float):
   
    results = model(frame, classes=[0], conf=conf_threshold, verbose=False)
    detections = []
    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = float(box.conf[0])
            detections.append({"bbox": [x1, y1, x2, y2], "conf": conf})
    return detections


def detect_persons_mock(frame: np.ndarray, frame_idx: int):
    
    rng = np.random.default_rng(frame_idx // 15)
    h, w = frame.shape[:2]
    n = int(rng.choice([0, 0, 1, 1, 1, 2, 2, 3], p=[0.15, 0.1, 0.2, 0.15, 0.1, 0.15, 0.1, 0.05]))
    detections = []
    for _ in range(n):
        x1 = float(rng.integers(50, w - 150))
        y1 = float(rng.integers(100, h - 250))
        x2 = x1 + float(rng.integers(80, 150))
        y2 = y1 + float(rng.integers(150, 250))
        conf = float(rng.uniform(0.4, 0.95))
        detections.append({"bbox": [x1, y1, x2, y2], "conf": conf})
    return detections


def classify_staff(frame: np.ndarray, bbox: list) -> bool:
   
    x1, y1, x2, y2 = [int(v) for v in bbox]
    roi = frame[max(0, y1):y2, max(0, x1):x2]
    if roi.size == 0:
        return False
    # Convert to HSV for colour analysis
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    # Compute saturation uniformity — staff uniforms have low saturation variance
    sat = hsv[:, :, 1].astype(float)
    sat_std = np.std(sat)
    val_mean = np.mean(hsv[:, :, 2])
    # Dark uniform: low value, moderate saturation
    is_dark_uniform = val_mean < 80 and sat_std < 40
    # High-saturation branded uniform (e.g. orange/red/green apron)
    branded_mask = (hsv[:, :, 1] > 150) & (hsv[:, :, 2] > 100)
    branded_ratio = np.sum(branded_mask) / max(branded_mask.size, 1)
    is_branded = branded_ratio > 0.35 and sat_std < 50
    return is_dark_uniform or is_branded


def infer_entry_exit_direction(bbox, frame_height, camera_type):
    cy = (bbox[1] + bbox[3]) / 2

    if camera_type == "ENTRY":
        return "ENTRY" if cy > frame_height * 0.6 else "EXIT"

    return "UNKNOWN"


def main():
    args = parse_args()

    # Resolve clip start time
    if args.clip_start:
        clip_start = datetime.fromisoformat(args.clip_start.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
    else:
        clip_start = datetime(2026, 4, 10, 10, 0, 0, tzinfo=timezone.utc)
        logger.info(f"No clip start provided — defaulting to {clip_start.isoformat()}")

    # Load layout
    layout = load_layout(args.layout) if Path(args.layout).exists() else {}

    # Determine camera type from ID
    camera_type = "ENTRY" if "ENTRY" in args.camera_id.upper() else (
        "BILLING" if "BILLING" in args.camera_id.upper() else "FLOOR"
    )

    # Load model
    model, backend = load_yolo_model(args.device)

    # Open video
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        logger.error(f"Cannot open video: {args.video}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    logger.info(
        f"Video: {args.video} | {frame_w}x{frame_h} @ {fps}fps | {total_frames} frames | "
        f"Store: {args.store_id} | Camera: {args.camera_id} | Type: {camera_type}"
    )

    # Initialise tracker and emitter
    tracker = MultiObjectTracker(max_lost=int(fps * 3), reid_threshold=0.45)
    zone_clf = ZoneClassifier(layout, args.store_id, frame_w, frame_h, camera_type)
    emitter = EventEmitter(
        store_id=args.store_id,
        camera_id=args.camera_id,
        output_path=args.output,
    )

    frame_idx = 0
    processed = 0
    t_start = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_idx += 1

        # Sample every N frames to match processing budget
        if frame_idx % args.fps_sample != 0:
            continue

        processed += 1
        timestamp = frame_to_timestamp(clip_start, frame_idx, fps)

        # Detect
        if backend == "ultralytics":
            raw_dets = detect_persons_ultralytics(model, frame, args.conf_threshold)
        else:
            raw_dets = detect_persons_mock(frame, frame_idx)

        if not raw_dets:
            # Handle zero-traffic frames — don't crash, just update tracker
            tracker.update([])
            continue

        # Classify staff for each detection
        for det in raw_dets:
            det["is_staff"] = classify_staff(frame, det["bbox"])

        # Update tracker — assigns/updates track IDs
        tracks = tracker.update(raw_dets)

        # Emit events per track
        for track in tracks:
            visitor_id = track["visitor_id"]
            bbox = track["bbox"]
            conf = track["conf"]
            is_staff = track.get("is_staff", False)
            status = track.get("status")  # "new", "active", "lost", "reentry"

            zone_id = zone_clf.classify(bbox)

            if status == "new":
                if camera_type == "ENTRY":
                    direction = infer_entry_exit_direction(
                 bbox,
                 frame_h,
                    camera_type
                    )
                    if direction == "ENTRY":
                        emitter.emit(
                            event_type="ENTRY",
                            visitor_id=visitor_id,
                            timestamp=timestamp,
                            zone_id=None,
                            dwell_ms=0,
                            is_staff=is_staff,
                            confidence=conf,
                            track=track,
                        )
                    else:
                        emitter.emit(
                            event_type="EXIT",
                            visitor_id=visitor_id,
                            timestamp=timestamp,
                            zone_id=None,
                            dwell_ms=0,
                            is_staff=is_staff,
                            confidence=conf,
                            track=track,
                        )
                else:
                    emitter.emit(
                        event_type="ZONE_ENTER",
                        visitor_id=visitor_id,
                        timestamp=timestamp,
                        zone_id=zone_id,
                        dwell_ms=0,
                        is_staff=is_staff,
                        confidence=conf,
                        track=track,
                    )

            elif status == "reentry":
                emitter.emit(
                    event_type="REENTRY",
                    visitor_id=visitor_id,
                    timestamp=timestamp,
                    zone_id=zone_id,
                    dwell_ms=0,
                    is_staff=is_staff,
                    confidence=conf,
                    track=track,
                )

            elif status == "active":
                dwell_ms = track.get("dwell_ms", 0)
                # Emit ZONE_DWELL every 30s of continued presence
                if dwell_ms > 0 and dwell_ms % 30000 < (1000 * args.fps_sample / fps):
                    emitter.emit(
                        event_type="ZONE_DWELL",
                        visitor_id=visitor_id,
                        timestamp=timestamp,
                        zone_id=zone_id,
                        dwell_ms=dwell_ms,
                        is_staff=is_staff,
                        confidence=conf,
                        track=track,
                    )
                # Billing queue events
                if zone_id == "BILLING" and not is_staff and camera_type == "BILLING":
                    queue_depth = tracker.get_billing_queue_depth()
                    if queue_depth > 1:
                        emitter.emit(
                            event_type="BILLING_QUEUE_JOIN",
                            visitor_id=visitor_id,
                            timestamp=timestamp,
                            zone_id=zone_id,
                            dwell_ms=dwell_ms,
                            is_staff=is_staff,
                            confidence=conf,
                            track=track,
                            metadata={"queue_depth": queue_depth},
                        )

            elif status == "lost":
                if camera_type == "ENTRY":
                    emitter.emit(
                        event_type="EXIT",
                        visitor_id=visitor_id,
                        timestamp=timestamp,
                        zone_id=None,
                        dwell_ms=track.get("dwell_ms", 0),
                        is_staff=is_staff,
                        confidence=conf,
                        track=track,
                    )
                else:
                    emitter.emit(
                        event_type="ZONE_EXIT",
                        visitor_id=visitor_id,
                        timestamp=timestamp,
                        zone_id=zone_id,
                        dwell_ms=track.get("dwell_ms", 0),
                        is_staff=is_staff,
                        confidence=conf,
                        track=track,
                    )

        if processed % 100 == 0:
            elapsed = time.time() - t_start
            logger.info(
                f"Processed {processed} sampled frames ({frame_idx}/{total_frames}) "
                f"in {elapsed:.1f}s — {emitter.event_count} events emitted"
            )

    cap.release()
    emitter.flush()

    elapsed = time.time() - t_start
    logger.info(
        f"Detection complete: {frame_idx} frames processed | "
        f"{emitter.event_count} events written to {args.output} | "
        f"{elapsed:.1f}s elapsed"
    )


if __name__ == "__main__":
    main()
