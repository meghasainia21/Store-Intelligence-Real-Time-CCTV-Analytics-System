#!/usr/bin/env bash

set -euo pipefail

CLIPS_DIR="${1:-./data/clips}"
OUTPUT_DIR="${2:-./data/events}"
API_BASE="${API_BASE:-http://localhost:8000}"
LAYOUT="${LAYOUT:-./data/store_layout.json}"

mkdir -p "$OUTPUT_DIR"

echo "=========================================="
echo " Store Intelligence — Detection Pipeline  "
echo "=========================================="
echo "Clips dir : $CLIPS_DIR"
echo "Output dir: $OUTPUT_DIR"
echo "API       : $API_BASE"
echo ""

process_clip() {
    local store_id="$1"
    local camera_id="$2"
    local video_file="$3"
    local clip_start="$4"
    local out_file="${OUTPUT_DIR}/${store_id}_${camera_id}.jsonl"

    echo "  [→] Processing ${store_id} / ${camera_id}: ${video_file}"

    python pipeline/detect.py \
        --video "$video_file" \
        --store-id "$store_id" \
        --camera-id "$camera_id" \
        --layout "$LAYOUT" \
        --output "$out_file" \
        --clip-start "$clip_start" \
        --conf-threshold 0.35 \
        --fps-sample 5 \
        --device cpu

    echo "  [✓] Events written to $out_file"
}

ingest_events() {
    local events_file="$1"
    local store_id="$2"

    echo "  [→] Ingesting $events_file into API..."

    # Read events in batches of 500
    python - <<PYEOF
import json, requests, sys

BATCH_SIZE = 500
events = []
total = 0
errors = 0

with open("${events_file}") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            errors += 1
            continue

        if len(events) >= BATCH_SIZE:
            r = requests.post(
                "${API_BASE}/events/ingest",
                json={"events": events},
                timeout=30,
            )
            if r.status_code not in (200, 207):
                print(f"  [!] Ingest error: {r.status_code} — {r.text[:200]}", file=sys.stderr)
            total += len(events)
            events = []

if events:
    r = requests.post(
        "${API_BASE}/events/ingest",
        json={"events": events},
        timeout=30,
    )
    total += len(events)

print(f"  Ingested {total} events (parse errors: {errors})")
PYEOF
}


if [ ! -d "$CLIPS_DIR" ]; then
    echo "WARNING: Clips directory not found at $CLIPS_DIR"
    echo "Falling back to generating synthetic events for demo..."
    python scripts/generate_synthetic_events.py \
        --store-id STORE_BLR_002 \
        --output "${OUTPUT_DIR}/STORE_BLR_002_synthetic.jsonl"
    STORE_ID="STORE_BLR_002"
    EVENTS_FILE="${OUTPUT_DIR}/STORE_BLR_002_synthetic.jsonl"
else
    for store_dir in "$CLIPS_DIR"/*/; do
        STORE_ID=$(basename "$store_dir")
        CLIP_START="2026-04-10T10:00:00Z"

        for camera_type in ENTRY FLOOR BILLING; do
            cam_id="CAM_${camera_type}_01"
            video_file=""

            # Match video file by name
            for ext in mp4 avi mov mkv; do
                candidate="${store_dir}${cam_id}.${ext}"
                if [ -f "$candidate" ]; then
                    video_file="$candidate"
                    break
                fi
                # Also try lowercase
                candidate="${store_dir}$(echo $cam_id | tr '[:upper:]' '[:lower:]').${ext}"
                if [ -f "$candidate" ]; then
                    video_file="$candidate"
                    break
                fi
            done

            if [ -z "$video_file" ]; then
                echo "  [!] No video found for ${STORE_ID}/${cam_id} — skipping"
                continue
            fi

            process_clip "$STORE_ID" "$cam_id" "$video_file" "$CLIP_START"
        done

        EVENTS_FILE="${OUTPUT_DIR}/${STORE_ID}_CAM_ENTRY_01.jsonl"
    done
fi

# Wait for API to be ready
echo ""
echo "Waiting for API to be ready..."
for i in $(seq 1 30); do
    if curl -sf "${API_BASE}/health" > /dev/null 2>&1; then
        echo "API is up!"
        break
    fi
    sleep 2
    echo "  Attempt $i/30..."
done

# Ingest all generated events
echo ""
echo "Ingesting events into Intelligence API..."
for events_file in "$OUTPUT_DIR"/*.jsonl; do
    [ -f "$events_file" ] || continue
    ingest_events "$events_file" "$STORE_ID"
done

echo ""
echo "=========================================="
echo " Pipeline complete!"
echo " Check metrics: ${API_BASE}/stores/STORE_BLR_002/metrics"
echo " Check health:  ${API_BASE}/health"
echo "=========================================="
