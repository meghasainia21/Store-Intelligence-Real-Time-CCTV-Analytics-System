import cv2
import time
import requests
import uuid
from datetime import datetime

API = "http://localhost:8000/events/ingest"

cap = cv2.VideoCapture(0)  # webcam

store_id = "STORE_BLR_002"
camera_id = "CAM_01"

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # 🔥 FAKE EVENT GENERATION (replace with YOLO later)
    event = {
        "event_id": str(uuid.uuid4()),
        "store_id": store_id,
        "camera_id": camera_id,
        "visitor_id": str(int(time.time()) % 1000),
        "event_type": "ENTRY",
        "timestamp": datetime.utcnow().isoformat(),
        "zone_id": "ENTRY",
        "dwell_ms": 0,
        "is_staff": 0,
        "confidence": 0.9,
        "metadata": {
            "queue_depth": 0,
            "sku_zone": None,
            "session_seq": 1
        }
    }

    try:
        requests.post(API, json={"events": [event]})
        print("event sent")
    except Exception as e:
        print("error:", e)

    time.sleep(2)