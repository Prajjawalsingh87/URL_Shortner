"""
database.py - Database connection and session management.
Uses SQLAlchemy with PostgreSQL.
All credentials are loaded from environment variables.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# PostgreSQL connection URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/urlshortener")

# Create SQLAlchemy engine with connection pooling for production
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


def get_db():
    """
    Dependency function for FastAPI routes.
    Yields a DB session and ensures it is closed after the request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
