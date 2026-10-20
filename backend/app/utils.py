"""
utils.py - Utility functions for URL validation and Base62 encoding.
"""

import re
import socket
import string
import asyncio
import hashlib
import ipaddress
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

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


# ──────────────────────────────────────────────
# Click analytics helpers
# ──────────────────────────────────────────────
_BOT_RE = re.compile(
    r"bot|crawler|spider|slurp|preview|facebookexternalhit|embedly|whatsapp|"
    r"telegram|discord|skype|curl/|wget|python|httpx|requests|go-http|okhttp|java/|headless",
    re.IGNORECASE,
)


def parse_user_agent(ua: str | None) -> tuple[str, str, str]:
    """Classify a user-agent string as (device, browser, os) without extra deps."""
    if not ua or ua == "unknown":
        return "unknown", "Unknown", "Unknown"

    if re.search(r"Edg(e|A|iOS)?/", ua):
        browser = "Edge"
    elif re.search(r"OPR/|Opera", ua):
        browser = "Opera"
    elif "SamsungBrowser/" in ua:
        browser = "Samsung Internet"
    elif re.search(r"Firefox/|FxiOS/", ua):
        browser = "Firefox"
    elif re.search(r"Chrome/|CriOS/", ua):
        browser = "Chrome"
    elif "Safari/" in ua and "Version/" in ua:
        browser = "Safari"
    elif re.match(r"curl/", ua, re.IGNORECASE):
        browser = "curl"
    else:
        browser = (re.split(r"[\s/;(]", ua, maxsplit=1)[0] or "Other")[:40]

    if "Windows" in ua:
        os_name = "Windows"
    elif re.search(r"iPhone|iPad|iPod", ua):
        os_name = "iOS"
    elif "Android" in ua:
        os_name = "Android"
    elif "CrOS" in ua:
        os_name = "ChromeOS"
    elif re.search(r"Mac OS X|Macintosh", ua):
        os_name = "macOS"
    elif "Linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Other"

    if _BOT_RE.search(ua):
        device = "bot"
    elif re.search(r"iPad|Tablet", ua) or ("Android" in ua and "Mobile" not in ua):
        device = "tablet"
    elif re.search(r"Mobi|iPhone|iPod|Android", ua):
        device = "mobile"
    else:
        device = "desktop"
    return device, browser, os_name


def referrer_host(referer: str | None) -> str | None:
    """Reduce a Referer header to its host (e.g. 'twitter.com'); None when absent."""
    if not referer:
        return None
    try:
        host = (urlsplit(referer).hostname or "").lower()
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host[:255] or None


# ──────────────────────────────────────────────
# Link preview (title / og:image / og:description)
# ──────────────────────────────────────────────
PREVIEW_TIMEOUT = 4.0              # seconds, per hop
PREVIEW_MAX_BYTES = 512 * 1024     # stop reading after 512 KB of HTML
PREVIEW_MAX_REDIRECTS = 3


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


async def _host_is_public(host: str, port: int) -> bool:
    """Resolve the host and require every address to be a public one (SSRF guard)."""
    try:
        return _is_public_ip(host)          # literal IP
    except ValueError:
        pass
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return False
    return bool(infos) and all(_is_public_ip(info[4][0]) for info in infos)


class _MetaParser(HTMLParser):
    """Collects <title> and the og:/twitter:/description <meta> tags from <head>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False
        self.done = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            a = {k.lower(): (v or "") for k, v in attrs}
            key = (a.get("property") or a.get("name") or "").lower().strip()
            if key and "content" in a and key not in self.meta:
                self.meta[key] = a["content"].strip()
        elif tag == "body":
            self.done = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "head":
            self.done = True

    def handle_data(self, data):
        if self._in_title and len(self.title) < 500:
            self.title += data


def _clean(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit] or None


async def fetch_link_preview(url: str) -> dict:
    """
    Fetch the page's title, og:description and og:image server-side.
    Safe by construction: http/https only, every hop's host must resolve to public
    IPs (no loopback/private/link-local/metadata), redirects followed manually,
    short timeout and a hard size cap. Never raises; returns {} on any problem.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; SnapLinkPreview/1.0; +https://snaplink-ten-eosin.vercel.app)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        }
        async with httpx.AsyncClient(follow_redirects=False, timeout=PREVIEW_TIMEOUT, headers=headers) as client:
            current = url
            for _ in range(PREVIEW_MAX_REDIRECTS + 1):
                parts = urlsplit(current)
                if parts.scheme not in ("http", "https") or not parts.hostname:
                    return {}
                port = parts.port or (443 if parts.scheme == "https" else 80)
                if not await _host_is_public(parts.hostname, port):
                    return {}
                async with client.stream("GET", current) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            return {}
                        current = urljoin(current, location)
                        continue
                    if resp.status_code >= 400:
                        return {}
                    if "html" not in resp.headers.get("content-type", "").lower():
                        return {}
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) >= PREVIEW_MAX_BYTES:
                            break
                    encoding = resp.encoding or "utf-8"
                    final_url = str(resp.url)
                    break
            else:
                return {}

        parser = _MetaParser()
        try:
            parser.feed(bytes(body).decode(encoding, errors="replace"))
        except Exception:
            pass
        m = parser.meta
        title = _clean(m.get("og:title") or m.get("twitter:title") or parser.title, 300)
        description = _clean(m.get("og:description") or m.get("twitter:description") or m.get("description"), 500)
        image = m.get("og:image") or m.get("og:image:url") or m.get("twitter:image")
        image_url = None
        if image:
            image_url = urljoin(final_url, image.strip())
            if urlsplit(image_url).scheme not in ("http", "https") or len(image_url) > 2000:
                image_url = None
        return {k: v for k, v in {"title": title, "description": description, "image_url": image_url}.items() if v}
    except Exception as e:
        logger.info(f"Link preview skipped for {url}: {e}")
        return {}
