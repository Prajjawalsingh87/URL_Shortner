"""
models.py - SQLAlchemy ORM models for the URL shortener.
Defines the 'urls' and 'clicks' database tables.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from .database import Base


class URL(Base):
    """
    Represents a shortened URL entry.
    Stores original URL, short code, and optional expiry/custom settings.
    """
    __tablename__ = "urls"

    id = Column(Integer, primary_key=True, index=True)
    original_url = Column(Text, nullable=False)             # The full original URL
    short_code = Column(String(20), unique=True, index=True, nullable=False)  # Base62 code
    custom_code = Column(Boolean, default=False)             # Was this a custom code?
    created_at = Column(DateTime, default=datetime.utcnow)  # Creation timestamp
    expires_at = Column(DateTime, nullable=True)             # Optional expiry
    is_active = Column(Boolean, default=True)               # Soft delete / deactivation

    # Relationship: one URL -> many Clicks
    clicks = relationship("Click", back_populates="url", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<URL(short_code={self.short_code}, original={self.original_url[:50]})>"


class Click(Base):
    """
    Represents an analytics record for each redirect event.
    Tracks IP, user-agent, and timestamp per click.
    """
    __tablename__ = "clicks"

    id = Column(Integer, primary_key=True, index=True)
    short_code = Column(String(20), ForeignKey("urls.short_code", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)   # When the click happened
    ip_address = Column(String(45), nullable=True)           # IPv4 or IPv6
    user_agent = Column(Text, nullable=True)                 # Browser/client user-agent

    # Relationship back to URL
    url = relationship("URL", back_populates="clicks")

    def __repr__(self):
        return f"<Click(short_code={self.short_code}, ip={self.ip_address}, ts={self.timestamp})>"
