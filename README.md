# 🧠 Store Intelligence — Real-Time CCTV Analytics Platform

A real-time AI-powered retail analytics system that transforms CCTV/event streams into actionable business insights such as visitor tracking, zone heatmaps, queue monitoring, and conversion analytics.

Built using FastAPI + async architecture with a live streaming dashboard powered by Server-Sent Events (SSE).

---

# 🚀 Features

## 📊 Real-Time Analytics
- Live visitor tracking (unique + total entries)
- Conversion rate (visitor → billing correlation)
- Queue depth monitoring (billing counter)
- Abandonment rate tracking
- Average dwell time computation

## 🧠 Behavioral Intelligence
- Zone-wise dwell time analytics
- Customer movement heatmaps
- Staff vs customer filtering
- Session-based tracking

## 🔥 Live Dashboard
- Real-time SSE streaming (updates every 5 seconds)
- Interactive KPI cards
- Zone heatmap visualization
- Live anomaly feed

## ⚙️ Backend System
- FastAPI async backend
- SQLite (WAL mode optimized)
- Idempotent event ingestion API
- POS transaction correlation engine
- Structured logging + health monitoring

---

# 🏗️ Architecture

CCTV / Video Stream (or Simulation)  
↓  
Event Detection Layer (YOLO / OpenCV / Script)  
↓  
FastAPI Ingestion API (/events/ingest)  
↓  
SQLite Database (events + pos_transactions)  
↓  
Metrics Engine (KPIs computation)  
↓  
SSE Streaming API (/dashboard/stream)  
↓  
Live Web Dashboard UI  

---


---

# 📁 Project Structure

```
store-intelligence/
│
├── app/
│   ├── main.py              # FastAPI entrypoint
│   ├── database.py          # DB setup + schema
│   ├── models.py            # Pydantic models
│   ├── metrics.py           # KPI computation engine
│   ├── anomalies.py         # anomaly detection logic
│   │
│   └── routers/
│       ├── events.py        # event ingestion APIs
│       ├── dashboard.py     # SSE streaming + UI
│       ├── stores.py
│       └── health.py
│
├── pipeline/
│   ├── live_cctv.py         # CCTV → event generator
│   ├── detect.py            # detection pipeline (optional)
│
├── scripts/
│   ├── ingest_events.py     # bulk ingestion script
│   ├── generate_synthetic_events.py
│
├── data/
│   ├── events/
│   ├── videos/
│   └── store_layout.json
│
├── docs/
│   └── dashboard.png
│
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```


# ⚙️ Tech Stack

- FastAPI (Async Python Backend)
- SQLite (WAL mode)
- Server-Sent Events (SSE)
- HTML + CSS + JavaScript Dashboard
- OpenCV / YOLO (for future CCTV integration)
- Docker (deployment ready)

---

# 🚀 Quick Start

## 1. Clone Repo
```bash
git clone https://github.com/your-username/store-intelligence.git
cd store-intelligence
```

### 2️. Create Virtual Environment

```bash
python -m venv venv
venv\Scripts\activate   # Windows

```

### 3.Install Dependencies

```bash
pip install -r requirements.txt

```

### 4. Run FastAPI Server

```bash
uvicorn app.main:app --reload

```

### 5. Open Dashboard
```bash
http://localhost:8000/dashboard

```
