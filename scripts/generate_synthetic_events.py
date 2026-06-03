import argparse
import json
import random
import uuid
from datetime import datetime, timedelta, timezone

ZONES = ["SKINCARE", "MAKEUP", "HAIRCARE", "FRAGRANCE", "BODYCARE", "NAILCARE", "BILLING"]
CAMERAS = ["CAM_ENTRY_01", "CAM_FLOOR_01", "CAM_BILLING_01"]

# Approximate traffic pattern based on POS data (Brigade Bangalore 10-Apr-2026)
# We had 101 transactions; typical conversion ~20-25%, so ~400-500 visitors
HOURLY_PATTERN = {
    10: 20, 11: 35, 12: 45, 13: 40, 14: 50,
    15: 55, 16: 65, 17: 70, 18: 75, 19: 80,
    20: 65, 21: 40, 22: 15,
}


def make_visitor_id():
    return "VIS_" + uuid.uuid4().hex[:6]


def iso_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_visitor_session(store_id: str, visitor_id: str, entry_time: datetime,
                              is_staff: bool, will_purchase: bool, rng: random.Random):
    events = []

    def ev(event_type, ts, zone_id=None, dwell_ms=0, cam_id="CAM_ENTRY_01", conf=None, meta=None):
        return {
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": cam_id,
            "visitor_id": visitor_id,
            "event_type": event_type,
            "timestamp": iso_ts(ts),
            "zone_id": zone_id,
            "dwell_ms": dwell_ms,
            "is_staff": is_staff,
            "confidence": round(conf or rng.uniform(0.6, 0.97), 4),
            "metadata": {
                "queue_depth": meta.get("queue_depth") if meta else None,
                "sku_zone": zone_id,
                "session_seq": len(events) + 1,
            }
        }

    t = entry_time
    events.append(ev("ENTRY", t))

    if is_staff:
        # Staff wander all zones
        for _ in range(rng.randint(3, 8)):
            t += timedelta(seconds=rng.randint(60, 300))
            zone = rng.choice(ZONES[:-1])
            events.append(ev("ZONE_ENTER", t, zone, cam_id="CAM_FLOOR_01"))
            dwell = rng.randint(30000, 180000)
            events.append(ev("ZONE_DWELL", t + timedelta(milliseconds=30000), zone, 30000, cam_id="CAM_FLOOR_01"))
            t += timedelta(milliseconds=dwell)
            events.append(ev("ZONE_EXIT", t, zone, dwell, cam_id="CAM_FLOOR_01"))
        t += timedelta(seconds=rng.randint(10, 60))
        events.append(ev("EXIT", t))
        return events

    # Customer journey
    num_zones = rng.randint(1, 4)
    visited_zones = rng.sample(ZONES[:-1], k=min(num_zones, len(ZONES) - 1))

    for zone in visited_zones:
        t += timedelta(seconds=rng.randint(15, 90))
        events.append(ev("ZONE_ENTER", t, zone, cam_id="CAM_FLOOR_01"))
        dwell = rng.randint(15000, 240000)
        # Emit ZONE_DWELL every 30s
        elapsed = 0
        while elapsed + 30000 < dwell:
            elapsed += 30000
            events.append(ev("ZONE_DWELL", t + timedelta(milliseconds=elapsed), zone,
                             elapsed, cam_id="CAM_FLOOR_01"))
        t += timedelta(milliseconds=dwell)
        events.append(ev("ZONE_EXIT", t, zone, dwell, cam_id="CAM_FLOOR_01"))

    if will_purchase:
        t += timedelta(seconds=rng.randint(10, 60))
        queue_depth = rng.randint(0, 4)
        billing_event = "BILLING_QUEUE_JOIN" if queue_depth > 0 else "ZONE_ENTER"
        events.append(ev(billing_event, t, "BILLING", 0, cam_id="CAM_BILLING_01",
                         meta={"queue_depth": queue_depth if queue_depth > 0 else None}))
        billing_dwell = rng.randint(60000, 480000)
        events.append(ev("ZONE_EXIT", t + timedelta(milliseconds=billing_dwell),
                         "BILLING", billing_dwell, cam_id="CAM_BILLING_01"))
        t += timedelta(milliseconds=billing_dwell)
    else:
        # Some abandon billing queue
        if rng.random() < 0.15 and len(visited_zones) > 0:
            t += timedelta(seconds=rng.randint(10, 30))
            events.append(ev("ZONE_ENTER", t, "BILLING", 0, cam_id="CAM_BILLING_01"))
            abandon_dwell = rng.randint(10000, 45000)
            t += timedelta(milliseconds=abandon_dwell)
            events.append(ev("BILLING_QUEUE_ABANDON", t, "BILLING", abandon_dwell,
                             cam_id="CAM_BILLING_01"))

    t += timedelta(seconds=rng.randint(10, 120))
    events.append(ev("EXIT", t))

    # Re-entry (5% chance)
    if rng.random() < 0.05:
        t += timedelta(seconds=rng.randint(120, 600))
        events.append(ev("REENTRY", t))

    return events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-id", default="STORE_BLR_002")
    parser.add_argument("--output", default="data/events/synthetic.jsonl")
    parser.add_argument("--date", default="2026-04-10")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    base_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    all_events = []
    visitor_count = 0

    for hour, approx_visitors in HOURLY_PATTERN.items():
        hour_start = base_date + timedelta(hours=hour)
        n_visitors = max(1, int(rng.gauss(approx_visitors, approx_visitors * 0.2)))
        n_staff = rng.randint(2, 5)

        for _ in range(n_staff):
            vid = make_visitor_id()
            offset = timedelta(seconds=rng.randint(0, 300))
            events = generate_visitor_session(
                args.store_id, vid, hour_start + offset,
                is_staff=True, will_purchase=False, rng=rng
            )
            all_events.extend(events)

        for _ in range(n_visitors):
            vid = make_visitor_id()
            offset = timedelta(seconds=rng.randint(0, 3600))
            # ~22% conversion based on POS data (101 txns / ~460 visitors)
            will_buy = rng.random() < 0.22
            events = generate_visitor_session(
                args.store_id, vid, hour_start + offset,
                is_staff=False, will_purchase=will_buy, rng=rng
            )
            all_events.extend(events)
            visitor_count += 1

    # Sort by timestamp
    all_events.sort(key=lambda e: e["timestamp"])

    import os
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        for event in all_events:
            f.write(json.dumps(event) + "\n")

    print(f"Generated {len(all_events)} events for {visitor_count} visitors → {args.output}")


if __name__ == "__main__":
    main()
