"""
models.py - SQLAlchemy ORM models for the URL shortener.
Defines the 'urls' and 'clicks' database tables.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, Index
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

    # Link preview metadata, fetched once when the link is created (all optional)
    title = Column(Text, nullable=True)                      # <title> / og:title
    description = Column(Text, nullable=True)                # og:description / meta description
    image_url = Column(Text, nullable=True)                  # og:image (absolute URL)

    # Ownership + protection (both optional: anonymous, unprotected links still work)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    password_hash = Column(Text, nullable=True)              # bcrypt hash; set = password-protected

    @property
    def is_protected(self) -> bool:
        return bool(self.password_hash)

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
    country = Column(String(8), nullable=True)               # ISO country code (from Vercel geo header)
    device = Column(String(20), nullable=True)               # desktop / mobile / tablet / bot
    browser = Column(String(40), nullable=True)              # Chrome, Safari, ...
    os = Column(String(40), nullable=True)                   # Windows, iOS, ...
    referrer = Column(String(255), nullable=True)            # Referring host, e.g. twitter.com

    # Relationship back to URL
    url = relationship("URL", back_populates="clicks")

    def __repr__(self):
        return f"<Click(short_code={self.short_code}, ip={self.ip_address}, ts={self.timestamp})>"


class User(Base):
    """An account. Links created while logged in are owned by the user."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(254), unique=True, index=True, nullable=False)   # stored lower-case
    password_hash = Column(Text, nullable=False)                           # bcrypt
    created_at = Column(DateTime, default=datetime.utcnow)


class RateEvent(Base):
    """
    One failed attempt (bad login, bad link password, sign-up) used for rate limiting.
    Kept in the database because serverless instances share no memory.
    """
    __tablename__ = "rate_events"

    id = Column(Integer, primary_key=True)
    bucket = Column(String(20), nullable=False)      # e.g. "login-email", "unlock"
    key = Column(String(300), nullable=False)        # e.g. email, "code:ip"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (Index("ix_rate_events_lookup", "bucket", "key", "created_at"),)
