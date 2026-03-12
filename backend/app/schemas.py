"""
schemas.py - Pydantic schemas for request validation and response serialization.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, HttpUrl, field_validator


class ShortenRequest(BaseModel):
    """Request body for POST /shorten"""
    url: str                                 # The original long URL
    custom_code: Optional[str] = None        # Optional custom short code
    expires_in_days: Optional[int] = None    # Optional expiry in days

    @field_validator("url")
    @classmethod
    def validate_url_format(cls, v):
        """Ensure URL has a valid scheme."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v

    @field_validator("custom_code")
    @classmethod
    def validate_custom_code(cls, v):
        """Custom code must be alphanumeric and 3-20 chars."""
        if v is not None:
            if not v.isalnum():
                raise ValueError("Custom code must be alphanumeric.")
            if len(v) < 3 or len(v) > 20:
                raise ValueError("Custom code must be 3-20 characters long.")
        return v


class ShortenResponse(BaseModel):
    """Response for POST /shorten"""
    short_url: str
    short_code: str
    original_url: str
    created_at: datetime
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PreviewResponse(BaseModel):
    """Response for GET /preview/{short_code}"""
    short_code: str
    original_url: str
    created_at: datetime
    total_clicks: int
    expires_at: Optional[datetime] = None


class ClickRecord(BaseModel):
    """Single click analytics entry"""
    timestamp: datetime
    ip_address: Optional[str]
    user_agent: Optional[str]

    class Config:
        from_attributes = True


class DailyClicks(BaseModel):
    """Clicks grouped by date"""
    date: str
    count: int


class AnalyticsResponse(BaseModel):
    """Response for GET /analytics/{short_code}"""
    short_code: str
    original_url: str
    total_clicks: int
    created_at: datetime
    expires_at: Optional[datetime] = None
    clicks_per_day: List[DailyClicks]
    recent_clicks: List[ClickRecord]
    top_user_agents: List[dict]
    top_ips: List[dict]


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    database: str
    cache: str
