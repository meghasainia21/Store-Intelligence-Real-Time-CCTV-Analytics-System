# DESIGN.md — Store Intelligence System Architecture

> 250+ words as required. Plain language. Honest about trade-offs.

## System Overview

The system is a three-layer pipeline: detection → events → API.

**Layer 1 — Detection Pipeline** (`pipeline/`): Reads CCTV frames using OpenCV, runs YOLOv8n for person detection, feeds detections into a ByteTrack-inspired tracker. The tracker assigns stable visitor IDs using IoU matching + colour histogram Re-ID. Each tracked person produces structured JSONL events (ENTRY, EXIT, ZONE_DWELL, etc.) which are written to disk.

**Layer 2 — Event Ingest** (`POST /events/ingest`): The API accepts batches of up to 500 events, validates them against the Pydantic schema, deduplicates by `event_id`, and writes to SQLite. Idempotency is guaranteed — posting the same batch twice produces zero duplicate rows.

**Layer 3 — Intelligence API** (`app/`): Five query endpoints compute real-time analytics from the event store. All queries exclude `is_staff=True`. Conversion rate is computed by correlating visitor presence in the BILLING zone with POS transaction timestamps (±5 minute window). If no POS data is present, billing zone arrivals are used as a proxy.

## Key Design Decisions

### SQLite + WAL mode
Chose SQLite with WAL journal mode over PostgreSQL for the submission. Simplifies the Docker setup (no separate container) and performs well for a single-store demo. At 40 stores sending events in real time, the first bottleneck would be write concurrency on the SQLite WAL — at which point Postgres or TimescaleDB would be the right migration path.

### Event-first Schema
Events are the source of truth. Metrics are computed on read, not materialised. This avoids stale aggregation tables at the cost of query latency for large event volumes. An optimisation path would be a Redis rolling counter for real-time KPIs and nightly SQLite aggregation tables for historical queries.

### Re-ID Approach
Used colour histogram (HSV, H+S channels, 32 bins each) rather than a deep Re-ID network (OSNet/torchreid). Rationale: no GPU in the evaluation environment, and histogram Re-ID handles the core re-entry case (same person returning after a brief exit) well enough. The failure mode — two people in similar clothing confusing the tracker — is logged at low confidence rather than silently promoted.

## AI-Assisted Decisions

1. **Schema Design**: Asked Claude to critique the initial event schema. It suggested adding `session_seq` (ordinal position of event in visitor session) to make funnel reconstruction easier. Agreed and included it. It also suggested a `data_confidence` flag on heatmap responses — adopted.

2. **Anomaly Thresholds**: Used Claude to reason through appropriate QUEUE_SPIKE thresholds for Indian beauty retail. Suggested WARN at 3, CRITICAL at 6 based on typical single-counter POS throughput. Adjusted from the initial suggestion of WARN=5 because Indian retail stores often have only 1-2 billing staff.

3. **Conversion Correlation**: Claude suggested using a 5-minute window before POS transaction timestamps to identify converted visitors. This was a direct improvement over my initial approach of simply checking whether a visitor had any BILLING event.
