# CHOICES.md — Three Key Decisions

## Decision 1: Detection Model — YOLOv8n

**Options considered**: YOLOv8n, YOLOv8s, RT-DETR, MediaPipe Pose, Faster R-CNN.

**What AI suggested**: Claude and ChatGPT both recommended YOLOv8s or YOLOv8m for better accuracy on partially occluded detections. GPT-4V analysis of sample retail footage suggested RT-DETR for its transformer-based global attention (better for crowded billing scenes).

**What I chose and why**: YOLOv8n. The evaluation environment is CPU-only. YOLOv8n processes 15fps footage at ~5fps on a modern laptop CPU without quantization — acceptable for our 5fps sampling rate. YOLOv8s was 2.4× slower with only ~3% mAP improvement on person detection. RT-DETR requires GPU to run at useful speed. The detection model runs offline on clips anyway, so throughput matters more than latency.

**Partial occlusion handling**: YOLOv8n degrades to lower confidence scores on partial occlusions rather than missing detections entirely. We pass ALL detections regardless of confidence (low-conf events are flagged, not dropped), which is the right call — a missed ENTRY is worse than a low-confidence one.

---

## Decision 2: Event Schema Design

**Options considered**:
- Minimal schema (just event_type + visitor_id + timestamp)
- Full schema with all analytics fields embedded
- Separate tables for different event types

**What AI suggested**: Claude recommended embedding `session_seq`, `queue_depth`, and `sku_zone` directly in the metadata object rather than as top-level fields. Reasoning: the core schema stays clean for all event types, and metadata can evolve without breaking the schema validator. I agreed.

**What I chose and why**: Single flat schema with a `metadata` object for event-specific fields. The `confidence` field is always present and never suppressed — a low confidence of 0.3 is useful signal, not noise. `is_staff` is a boolean on every event so any query can trivially exclude staff without a join.

**Where I disagreed with AI**: Claude initially suggested separate `visitor_events` and `zone_events` tables. Rejected this — it complicates session reconstruction queries significantly. A single `events` table with composite indexes on `(store_id, timestamp)` and `(store_id, visitor_id)` handles all our query patterns efficiently.

---

## Decision 3: SQLite vs PostgreSQL

**Options considered**: SQLite + WAL, PostgreSQL, PostgreSQL + TimescaleDB, DuckDB.

**What AI suggested**: Claude recommended PostgreSQL for production readiness and TimescaleDB for time-series query performance on large event volumes. It made a solid argument: at 40 stores × 500 events/minute = 20,000 inserts/min, SQLite WAL starts struggling around 10,000 writes/minute on typical hardware.

**What I chose and why**: SQLite with WAL mode for the submission. The acceptance gate requires `docker compose up` with no manual steps. SQLite needs zero configuration — no separate container, no connection strings, no initial setup. For a demo with synthetic events, SQLite is perfectly adequate.

**Migration path**: If this were production, I'd migrate to PostgreSQL with a `store_id + timestamp` partition key and a Redis sorted set for real-time queue depth (avoiding full table scans for the anomaly detector). The app layer is storage-agnostic by design — the `database.py` module would be the only file to change.

**Where I disagreed with AI**: Claude suggested DuckDB for analytical queries. Interesting idea — DuckDB's columnar engine would dramatically speed up the heatmap and funnel aggregations. But DuckDB has limited concurrent write support, which conflicts with real-time event ingest. Rejected for now, noted as a future optimisation for read replicas.
