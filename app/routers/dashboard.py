import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse

from app.database import get_db
from app.metrics import compute_metrics
from app.anomalies import detect_anomalies

logger = logging.getLogger("dashboard")
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stream/{store_id}")
async def metric_stream(store_id: str):

    async def event_generator():
        while True:
            try:
                db = await get_db()

                # FIX: always use proper date
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

                metrics = await compute_metrics(db, store_id, date_str)
                anomalies = await detect_anomalies(db, store_id)

                payload = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "store_id": store_id,
                    "metrics": {
                        "unique_visitors": metrics.unique_visitors,
                        "conversion_rate": metrics.conversion_rate,
                        "avg_dwell_ms": metrics.avg_dwell_ms,
                        "queue_depth": metrics.queue_depth,
                        "abandonment_rate": metrics.abandonment_rate,
                        "total_entries": metrics.total_entries,
                        "zone_dwells": [z.dict() for z in metrics.zone_dwells],
                    },
                    "anomalies": [a.dict() for a in anomalies.anomalies],
                }

                yield f"data: {json.dumps(payload)}\n\n"

            except Exception as e:
                logger.error(f"SSE error: {e}")
                yield f"data: {json.dumps({'metrics': {}, 'anomalies': [], 'error': str(e)})}\n\n"

            await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    return HTMLResponse(content=_DASHBOARD_HTML)


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Store Intelligence — Live Dashboard</title>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

:root {
  --bg: #070A12;
  --surface: rgba(255,255,255,0.06);
  --surface-2: rgba(255,255,255,0.09);
  --border: rgba(255,255,255,0.08);

  --accent: #8b5cf6;
  --accent2: #06b6d4;
  --warn: #f59e0b;
  --danger: #ef4444;
  --success: #22c55e;

  --text: #e5e7eb;
  --muted: #94a3b8;

  --radius: 16px;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: 'Inter', sans-serif;
  background:
    radial-gradient(circle at 10% 10%, rgba(139,92,246,0.18), transparent 40%),
    radial-gradient(circle at 90% 20%, rgba(6,182,212,0.12), transparent 40%),
    var(--bg);
  color: var(--text);
  min-height: 100vh;
}

/* HEADER */
header {
  padding: 1rem 2rem;
  background: var(--surface);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

header h1 {
  font-size: 1.2rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.store-selector {
  padding: 0.5rem 1rem;
  border-radius: 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  font-size: 0.85rem;
  outline: none;
}

.badge {
  padding: 0.25rem 0.7rem;
  border-radius: 999px;
  font-size: 0.7rem;
  background: rgba(34,197,94,0.15);
  border: 1px solid rgba(34,197,94,0.4);
}

.badge.live {
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%,100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.05); opacity: 0.6; }
}

/* GRID */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 1rem;
  padding: 1.5rem;
}

/* CARDS */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.2rem;
  backdrop-filter: blur(18px);
  transition: all 0.25s ease;
  position: relative;
  overflow: hidden;
}

.card:hover {
  transform: translateY(-4px);
  border-color: rgba(139,92,246,0.5);
  background: var(--surface-2);
}

.card::before {
  content: "";
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at top left, rgba(139,92,246,0.15), transparent 40%);
  opacity: 0;
  transition: 0.3s;
}

.card:hover::before {
  opacity: 1;
}

.card-label {
  font-size: 0.7rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.12em;
}

.card-value {
  font-size: 2rem;
  font-weight: 700;
  margin-top: 0.4rem;
}

.card-sub {
  font-size: 0.75rem;
  color: var(--muted);
  margin-top: 0.2rem;
}

.card-value.good { color: var(--success); }
.card-value.warn { color: var(--warn); }
.card-value.danger { color: var(--danger); }

/* SECTIONS */
.section {
  padding: 0 1.5rem 1.5rem;
}

.section h2 {
  font-size: 0.75rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.15em;
  margin-bottom: 1rem;
}

/* ZONES */
.zone-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 0.8rem;
}

.zone-tile {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 0.8rem;
  position: relative;
  overflow: hidden;
  transition: 0.2s;
}

.zone-tile:hover {
  transform: scale(1.03);
  border-color: var(--accent2);
}

.zone-name {
  font-size: 0.7rem;
  color: var(--muted);
}

.zone-score {
  font-size: 1.4rem;
  font-weight: 700;
  margin-top: 0.3rem;
}

.zone-dwell {
  font-size: 0.65rem;
  color: var(--muted);
}

.heat-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
}

/* ANOMALIES */
.anomaly-list {
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}

.anomaly {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 4px solid var(--muted);
  padding: 0.8rem;
  border-radius: 12px;
}

.anomaly.WARN { border-left-color: var(--warn); }
.anomaly.CRITICAL {
  border-left-color: var(--danger);
  box-shadow: 0 0 20px rgba(239,68,68,0.15);
}
.anomaly.INFO { border-left-color: var(--accent2); }

.anomaly-type {
  font-weight: 600;
  font-size: 0.75rem;
}

.anomaly-desc {
  font-size: 0.75rem;
  color: var(--muted);
  margin-top: 0.2rem;
}

.anomaly-action {
  font-size: 0.7rem;
  color: var(--accent2);
  margin-top: 0.3rem;
}

/* STATUS BAR */
.status-bar {
  padding: 0.6rem 2rem;
  display: flex;
  justify-content: space-between;
  font-size: 0.7rem;
  color: var(--muted);
  border-top: 1px solid var(--border);
  background: var(--surface);
  backdrop-filter: blur(12px);
}

/* FUNNEL */
.funnel {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
  height: 130px;
}

.funnel-bar {
  width: 100%;
  background: linear-gradient(180deg, var(--accent), var(--accent2));
  border-radius: 8px 8px 0 0;
}

/* RESPONSIVE */
@media (max-width: 768px) {
  header { flex-direction: column; gap: 0.8rem; }
}
</style>
</head>

<body>

<header>
  <h1>⬡ Store Intelligence</h1>
  <div style="display:flex;gap:1rem;align-items:center;">
    <select class="store-selector" id="store-select" onchange="switchStore(this.value)">
      <option value="STORE_BLR_002">Brigade Bangalore</option>
    </select>
    <span class="badge live" id="live-badge">● LIVE</span>
  </div>
</header>

<div class="grid">
  <div class="card"><div class="card-label">Unique Visitors</div><div class="card-value" id="kpi-visitors">—</div></div>
  <div class="card"><div class="card-label">Conversion Rate</div><div class="card-value" id="kpi-conv">—</div></div>
  <div class="card"><div class="card-label">Avg Dwell</div><div class="card-value" id="kpi-dwell">—</div></div>
  <div class="card"><div class="card-label">Queue Depth</div><div class="card-value" id="kpi-queue">—</div></div>
  <div class="card"><div class="card-label">Abandonment</div><div class="card-value" id="kpi-abandon">—</div></div>
  <div class="card"><div class="card-label">Entries</div><div class="card-value" id="kpi-entries">—</div></div>
</div>

<div class="section">
  <h2>Zone Heatmap</h2>
  <div class="zone-grid" id="zone-grid"></div>
</div>

<div class="section">
  <h2>Anomalies</h2>
  <div class="anomaly-list" id="anomaly-list"></div>
</div>

<div class="status-bar">
  <span>Last update: <span id="last-update">connecting...</span></span>
  <span id="event-count">Events: —</span>
</div>

<script>
let currentStore = 'STORE_BLR_002';
let es;

function switchStore(id){
  currentStore = id;
  if(es) es.close();
  connect();
}

function connect(){
  es = new EventSource(`/dashboard/stream/${currentStore}`);
  es.onmessage = e => update(JSON.parse(e.data));
}

function update(data){
  const m = data.metrics;

  document.getElementById('kpi-visitors').textContent = m.unique_visitors;
  document.getElementById('kpi-conv').textContent = (m.conversion_rate*100).toFixed(1)+'%';
  document.getElementById('kpi-dwell').textContent = (m.avg_dwell_ms/60000).toFixed(1)+'m';
  document.getElementById('kpi-queue').textContent = m.queue_depth;
  document.getElementById('kpi-abandon').textContent = (m.abandonment_rate*100).toFixed(1)+'%';
  document.getElementById('kpi-entries').textContent = m.total_entries;

  document.getElementById('last-update').textContent =
    new Date(data.timestamp).toLocaleTimeString();

  // zones
  const zg = document.getElementById('zone-grid');
  zg.innerHTML = '';
  (m.zone_dwells||[]).forEach(z=>{
    const div = document.createElement('div');
    div.className = 'zone-tile';
    const h = Math.min(100, (z.avg_dwell_ms/120000)*100);
    div.innerHTML = `
      <div class="zone-name">${z.zone_id}</div>
      <div class="zone-score">${Math.round(h)}</div>
      <div class="zone-dwell">${(z.avg_dwell_ms/60000).toFixed(1)}m</div>
      <div class="heat-bar" style="width:${h}%"></div>
    `;
    zg.appendChild(div);
  });

  // anomalies
  const al = document.getElementById('anomaly-list');
  al.innerHTML = (data.anomalies||[]).map(a=>`
    <div class="anomaly ${a.severity}">
      <div class="anomaly-type">${a.anomaly_type}</div>
      <div class="anomaly-desc">${a.description}</div>
      <div class="anomaly-action">${a.suggested_action}</div>
    </div>
  `).join('');
}

connect();
</script>

</body>
</html>"""