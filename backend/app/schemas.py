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
    title: Optional[str] = None              # Link preview: page title
    description: Optional[str] = None        # Link preview: og:description
    image_url: Optional[str] = None          # Link preview: og:image

    class Config:
        from_attributes = True


BULK_MAX_URLS = 20


class BulkShortenRequest(BaseModel):
    """Request body for POST /shorten/bulk"""
    urls: List[str]                          # 1-20 URLs; blank entries are ignored
    expires_in_days: Optional[int] = None    # Applied to every link

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, v):
        v = [u.strip() for u in v if u and u.strip()]
        if not v:
            raise ValueError("Provide at least one URL.")
        if len(v) > BULK_MAX_URLS:
            raise ValueError(f"You can shorten at most {BULK_MAX_URLS} URLs at once.")
        if any(len(u) > 2048 for u in v):
            raise ValueError("Each URL must be at most 2048 characters.")
        return v


class BulkItem(BaseModel):
    """One line of a bulk request: either a created link or an error."""
    input: str
    ok: bool
    error: Optional[str] = None
    link: Optional[ShortenResponse] = None


class BulkShortenResponse(BaseModel):
    """Response for POST /shorten/bulk"""
    total: int
    succeeded: int
    failed: int
    results: List[BulkItem]


class PreviewResponse(BaseModel):
    """Response for GET /preview/{short_code}"""
    short_code: str
    original_url: str
    created_at: datetime
    total_clicks: int
    expires_at: Optional[datetime] = None
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None


class ClickRecord(BaseModel):
    """Single click analytics entry"""
    timestamp: datetime
    ip_address: Optional[str]
    user_agent: Optional[str]
    country: Optional[str] = None
    device: Optional[str] = None
    browser: Optional[str] = None
    os: Optional[str] = None
    referrer: Optional[str] = None

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
    top_countries: List[dict] = []           # [{"name": "IN", "count": 3}, ...]
    top_devices: List[dict] = []
    top_browsers: List[dict] = []
    top_os: List[dict] = []
    top_referrers: List[dict] = []
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    database: str
    cache: str
