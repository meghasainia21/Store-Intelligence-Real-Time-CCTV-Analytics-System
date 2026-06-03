#!/usr/bin/env python3
"""scripts/ingest_events.py — Bulk-ingest a JSONL events file into the API."""

import argparse, json, sys
import requests

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--batch-size", type=int, default=500)
    args = p.parse_args()

    events, total, errors = [], 0, 0
    with open(args.file) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try: events.append(json.loads(line))
            except: errors += 1; continue
            if len(events) >= args.batch_size:
                r = requests.post(f"{args.api}/events/ingest", json={"events": events}, timeout=30)
                total += len(events); events = []
                if r.status_code not in (200, 207):
                    print(f"Error: {r.status_code}", file=sys.stderr)
    if events:
        requests.post(f"{args.api}/events/ingest", json={"events": events}, timeout=30)
        total += len(events)
    print(f"Ingested {total} events (parse errors: {errors})")

if __name__ == "__main__":
    main()
