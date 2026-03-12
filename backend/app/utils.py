"""
utils.py - Utility functions for URL validation and Base62 encoding.
"""

import re
import string
import hashlib
import httpx
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# Base62 character set
BASE62_CHARS = string.digits + string.ascii_letters  # 0-9, a-z, A-Z


def encode_base62(num: int) -> str:
    """
    Convert an integer to a Base62 string.
    Used to generate compact short codes from numeric IDs or hashes.
    """
    if num == 0:
        return BASE62_CHARS[0]

    result = []
    base = len(BASE62_CHARS)
    while num > 0:
        result.append(BASE62_CHARS[num % base])
        num //= base
    return "".join(reversed(result))


def generate_short_code(original_url: str, length: int = 7) -> str:
    """
    Generate a unique short code using MD5 hash of the URL.
    Takes first `length` characters of the Base62-encoded hash integer.
    This is deterministic for the same URL — prevents exact duplicates.
    """
    hash_bytes = hashlib.md5(original_url.encode()).digest()
    hash_int = int.from_bytes(hash_bytes, byteorder="big")
    code = encode_base62(hash_int)
    return code[:length]


def is_valid_url(url: str) -> bool:
    """
    Validate URL format using regex.
    Checks that the URL has a valid scheme, domain, and optional path.
    """
    pattern = re.compile(
        r"^https?://"                            # http:// or https://
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)"    # subdomain/domain
        r"+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"            # TLD
        r"localhost|"                            # or localhost
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})" # or IP
        r"(?::\d+)?"                             # optional port
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE
    )
    return bool(pattern.match(url))


async def is_url_reachable(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """
    Async HTTP HEAD/GET request to verify the URL is reachable.
    Returns (True, "OK") on success, (False, error_message) on failure.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.head(url)
            if response.status_code < 400:
                return True, "OK"
            # Try GET if HEAD fails
            response = await client.get(url)
            if response.status_code < 400:
                return True, "OK"
            return False, f"Server returned status {response.status_code}"
    except httpx.TimeoutException:
        return False, "Request timed out — URL may be slow or unreachable"
    except httpx.ConnectError:
        return False, "Connection failed — check URL spelling and network"
    except Exception as e:
        logger.warning(f"URL reachability check failed for {url}: {e}")
        return False, str(e)


def calculate_expiry(expires_in_days: int | None) -> datetime | None:
    """Calculate expiry datetime from days, or return None if no expiry."""
    if expires_in_days and expires_in_days > 0:
        return datetime.utcnow() + timedelta(days=expires_in_days)
    return None


def is_expired(expires_at: datetime | None) -> bool:
    """Check if a URL has expired."""
    if expires_at is None:
        return False
    return datetime.utcnow() > expires_at
