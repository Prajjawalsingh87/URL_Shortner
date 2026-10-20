"""
database.py - Database connection and session management.
Uses SQLAlchemy with PostgreSQL.
All credentials are loaded from environment variables.
"""

import os
from sqlalchemy import create_engine, inspect, text
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

# Columns added after the first release. There are no migrations, so they are added
# in place (nullable, idempotent) for databases created by an older version.
ADDED_COLUMNS = {
    "urls": {
        "title": "TEXT",
        "description": "TEXT",
        "image_url": "TEXT",
        "owner_id": "INTEGER",        # FK to users.id on fresh databases
        "password_hash": "TEXT",
    },
    "clicks": {
        "country": "VARCHAR(8)",
        "device": "VARCHAR(20)",
        "browser": "VARCHAR(40)",
        "os": "VARCHAR(40)",
        "referrer": "VARCHAR(255)",
    },
}


def _add_missing_columns():
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            for table, cols in ADDED_COLUMNS.items():
                for name, ddl in cols.items():
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {ddl}"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_urls_owner_id ON urls (owner_id)"))
        else:
            # SQLite (local dev) has no ADD COLUMN IF NOT EXISTS: check first.
            for table, cols in ADDED_COLUMNS.items():
                existing = {c["name"] for c in inspect(conn).get_columns(table)}
                for name, ddl in cols.items():
                    if name not in existing:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_urls_owner_id ON urls (owner_id)"))


def ensure_tables():
    """Create tables and add any newer columns once per process (idempotent).
    Serverless runtimes may skip the app's startup event, so this also runs on
    the first request."""
    global _tables_ready
    if not _tables_ready:
        from . import models  # noqa: F401  (register models on Base)
        Base.metadata.create_all(bind=engine)
        _add_missing_columns()
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
