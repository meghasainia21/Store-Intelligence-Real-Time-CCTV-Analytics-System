"""
main.py — Store Intelligence API entrypoint (FIXED VERSION)
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import init_db
from app.routers import events, stores, health as health_router, dashboard as dashboard_router
from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger("main")


# =========================
# LIFESPAN (IMPORTANT FIX)
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Store Intelligence API")

    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"DB init failed: {e}")
        raise

    yield

    logger.info("Store Intelligence API shutting down")


app = FastAPI(
    title="Store Intelligence API",
    description="Real-time retail analytics from CCTV event streams",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# =========================
# CORS
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# REQUEST LOGGER
# =========================
@app.middleware("http")
async def structured_logging_middleware(request: Request, call_next):
    trace_id = str(uuid.uuid4())
    request.state.trace_id = trace_id

    start = time.perf_counter()

    try:
        response = await call_next(request)
        latency_ms = (time.perf_counter() - start) * 1000

        log_data = {
            "trace_id": trace_id,
            "method": request.method,
            "endpoint": request.url.path,
            "latency_ms": round(latency_ms, 2),
            "status_code": response.status_code,
        }

        ec = response.headers.get("X-Event-Count")
        if ec:
            log_data["event_count"] = int(ec)

        logger.info("request", extra=log_data)

        response.headers["X-Trace-Id"] = trace_id
        return response

    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000

        logger.error(
            "unhandled_exception",
            extra={
                "trace_id": trace_id,
                "endpoint": request.url.path,
                "latency_ms": round(latency_ms, 2),
                "error": str(exc),
            },
            exc_info=True,
        )

        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "trace_id": trace_id,
            },
        )


# =========================
# DB HEALTH GATE (FIXED)
# =========================
@app.middleware("http")
async def db_health_gate(request: Request, call_next):
    skip_paths = {"/health", "/docs", "/redoc", "/openapi.json"}

    if request.url.path in skip_paths:
        return await call_next(request)

    try:
        from app.database import get_db
        db = await get_db()
        await db.execute("SELECT 1")
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "error": "service_unavailable",
                "message": "Database not ready or not initialized",
            },
        )

    return await call_next(request)


# =========================
# ROUTERS
# =========================
app.include_router(events.router)
app.include_router(stores.router)
app.include_router(health_router.router)
app.include_router(dashboard_router.router)


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": "Store Intelligence API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }