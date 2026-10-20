"""
database.py - Database connection and session management.
Uses SQLAlchemy with PostgreSQL.
All credentials are loaded from environment variables.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

# PostgreSQL connection URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/urlshortener")
# Hosted providers (Neon, Heroku-style) hand out postgres://, which SQLAlchemy 2 rejects
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

# Serverless (Vercel): every invocation is short-lived, so keep no idle connections
# and let the provider's pooler (e.g. Neon's -pooler host) do the pooling.
SERVERLESS = bool(os.getenv("VERCEL"))

if SERVERLESS:
    engine = create_engine(DATABASE_URL, poolclass=NullPool, pool_pre_ping=True, echo=False)
else:
    # Long-running server: connection pooling for production
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,       # Verify connection before using it
        pool_size=10,              # Max 10 persistent connections
        max_overflow=20,           # Allow 20 extra temporary connections
        pool_recycle=3600,         # Recycle connections every 1 hour
        echo=False,                # Set True for SQL debug logging
    )

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for all ORM models
Base = declarative_base()

_tables_ready = False


def ensure_tables():
    """Create tables once per process (idempotent). Serverless runtimes may skip
    the app's startup event, so this also runs on the first request."""
    global _tables_ready
    if not _tables_ready:
        from . import models  # noqa: F401  (register models on Base)
        Base.metadata.create_all(bind=engine)
        _tables_ready = True


def get_db():
    """
    Dependency function for FastAPI routes.
    Yields a DB session and ensures it is closed after the request.
    """
    ensure_tables()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
