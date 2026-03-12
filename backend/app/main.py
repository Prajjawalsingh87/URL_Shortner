"""
main.py - FastAPI application entry point.
Configures CORS, lifespan events, and mounts all routers.
"""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from .database import engine, Base
from .routes import router
from .cache import init_redis, close_redis

# ──────────────────────────────────────────────
# Logging Configuration
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Lifespan: startup & shutdown events
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    logger.info("🚀 Starting URL Shortener service...")

    # Create all database tables (idempotent)
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables ready")

    # Initialize Redis connection
    await init_redis()

    yield  # App runs here

    # Cleanup on shutdown
    logger.info("🛑 Shutting down...")
    await close_redis()


# ──────────────────────────────────────────────
# FastAPI App Instance
# ──────────────────────────────────────────────
app = FastAPI(
    title="URL Shortener API",
    description=(
        "Production-ready URL shortener with analytics. "
        "Supports Base62 short codes, Redis caching, and click tracking."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ──────────────────────────────────────────────
# CORS Middleware
# Allow the frontend origin to call backend APIs
# ──────────────────────────────────────────────
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:5500,http://127.0.0.1:5500"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# Mount Routes
# ──────────────────────────────────────────────
app.include_router(router)


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint — confirms service is running."""
    return {
        "service": "URL Shortener API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }
