"""One allowlisted origin, bounded GETs, robots policy, pacing and an LRU cache."""

import asyncio
import json
import math
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.robotparser import RobotFileParser

import httpx

from app.errors import ApiError
from app.models import SourceMeta
from app.parser import ORIGIN, SLUG

USER_AGENT = "BookBridge/1.0 (read-only assignment; books.toscrape.com sandbox)"
ALLOWED_PATH = re.compile(
    rf"^/(?:robots\.txt|catalogue/(?:page-[1-9][0-9]*\.html|{SLUG}/index\.html|"
    rf"category/books/{SLUG}/(?:index|page-[1-9][0-9]*)\.html))?$"
)


@dataclass(frozen=True)
class Settings:
    mode: str = "live"
    cache_ttl: float = 300
    cache_size: int = 32
    min_interval: float = 1.0
    timeout: float = 8.0
    max_bytes: int = 2_000_000
    retries: int = 2
    max_retry_wait: float = 5.0
    robots_ttl: float = 3600
    api_requests_per_minute: int = 60
    request_timeout: float = 45


@dataclass(frozen=True)
class Page:
    html: str
    source: SourceMeta


def retry_after_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        if value.isdigit():
            return int(value)
        date = parsedate_to_datetime(value)
        return max(0, math.ceil((date - datetime.now(UTC)).total_seconds()))
    except (ValueError, TypeError, OverflowError):
        return None


def fixture_transport(directory: Path) -> tuple[httpx.MockTransport, datetime]:
    manifest = json.loads((directory / "manifest.json").read_text())
    by_path = {entry["path"]: (name, entry) for name, entry in manifest["files"].items()}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path not in by_path:
            raise ApiError(
                503, "FIXTURE_NOT_RECORDED", "This page is not in the offline fixture set. Use live mode."
            )
        name, entry = by_path[request.url.path]
        return httpx.Response(
            entry["status"],
            content=(directory / name).read_bytes(),
            headers={"content-type": entry["content_type"]},
        )

    return httpx.MockTransport(handler), datetime.fromisoformat(manifest["captured_at"])


class CatalogueSource:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        fixture_time: datetime | None = None,
    ):
        self.settings = settings
        self.client = httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            timeout=settings.timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"},
        )
        self._lock = asyncio.Lock()
        self._cache: OrderedDict[str, tuple[float, Page]] = OrderedDict()
        self._next_request = 0.0
        self._blocked_until = 0.0
        self._robots: RobotFileParser | None = None
        self._robots_expires = 0.0
        self.fixture_time = fixture_time
        self.request_count = 0

    async def close(self) -> None:
        await self.client.aclose()

    def invalidate(self, path: str) -> None:
        self._cache.pop(path, None)

    async def get(self, path: str) -> Page:
        if not ALLOWED_PATH.fullmatch(path) or path == "/robots.txt":
            raise ApiError(400, "INVALID_SOURCE_PATH", "Only known catalogue paths are supported.")
        # Serialisation makes pacing global and coalesces identical concurrent cache misses.
        async with self._lock:
            now = time.monotonic()
            if self._robots is None or now >= self._robots_expires:
                await self._load_robots()
            if not self._robots.can_fetch("BookBridge", ORIGIN + path):
                raise ApiError(503, "ROBOTS_DENIED", "The source robots policy does not allow this page.")
            cached = self._cache.get(path)
            if cached and cached[0] > time.monotonic():
                self._cache.move_to_end(path)
                return replace(cached[1], source=cached[1].source.model_copy(update={"cache_hit": True}))
            status, html = await self._download(path)
            if status == 404:
                raise ApiError(404, "NOT_FOUND", "The requested catalogue page or book was not found.")
            page = Page(
                html=html,
                source=SourceMeta(
                    mode=self.settings.mode,
                    source_url=ORIGIN + path,
                    fetched_at=self.fixture_time or datetime.now(UTC),
                    cache_hit=False,
                ),
            )
            self._cache[path] = (time.monotonic() + self.settings.cache_ttl, page)
            self._cache.move_to_end(path)
            while len(self._cache) > self.settings.cache_size:
                self._cache.popitem(last=False)
            return page

    async def _load_robots(self) -> None:
        status, body = await self._download("/robots.txt", robots=True)
        policy = RobotFileParser()
        # A genuine 404 means no robots file. Access-denied and unavailable are not treated as permission.
        if status == 404:
            body = "User-agent: *\nAllow: /\n"
        policy.parse(body.splitlines())
        self._robots = policy
        self._robots_expires = time.monotonic() + self.settings.robots_ttl

    async def _download(self, path: str, robots: bool = False) -> tuple[int, str]:
        for attempt in range(self.settings.retries + 1):
            now = time.monotonic()
            if self._blocked_until > now:
                raise ApiError(
                    503,
                    "UPSTREAM_COOLDOWN",
                    "The upstream server requested a cooldown.",
                    max(1, math.ceil(self._blocked_until - now)),
                )
            crawl_delay = self._robots.crawl_delay("BookBridge") if self._robots else None
            interval = max(self.settings.min_interval, float(crawl_delay or 0))
            await asyncio.sleep(max(0, self._next_request - now))
            self._next_request = time.monotonic() + interval
            self.request_count += 1
            delay = 0.5 * (2**attempt)
            try:
                async with asyncio.timeout(self.settings.timeout):
                    async with self.client.stream("GET", ORIGIN + path) as response:
                        status = response.status_code
                        if status in (401, 403):
                            raise ApiError(
                                502,
                                "SOURCE_ACCESS_DENIED",
                                "The source denied access; no bypass is attempted.",
                            )
                        if status == 404:
                            return 404, ""
                        if 300 <= status < 400:
                            raise ApiError(
                                502, "SOURCE_REDIRECT", "An unexpected upstream redirect was refused."
                            )
                        if status in (429, 500, 502, 503, 504):
                            after = retry_after_seconds(response.headers.get("retry-after"))
                            delay = max(delay, float(after or 0))
                            # Persist explicit cooldowns even if this caller cancels its retry sleep.
                            if after is not None or status == 429:
                                self._blocked_until = time.monotonic() + delay
                            if delay > self.settings.max_retry_wait or attempt == self.settings.retries:
                                cooldown = max(1, math.ceil(delay))
                                self._blocked_until = time.monotonic() + cooldown
                                raise ApiError(
                                    503,
                                    "UPSTREAM_UNAVAILABLE",
                                    "The source is busy or temporarily unavailable.",
                                    cooldown,
                                )
                        elif status != 200:
                            raise ApiError(
                                502, "UPSTREAM_HTTP_ERROR", "The source returned an unexpected HTTP status."
                            )
                        else:
                            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                            permitted = {"text/plain"} if robots else {"text/html", "application/xhtml+xml"}
                            if mime not in permitted:
                                raise ApiError(
                                    502,
                                    "SOURCE_CONTENT_TYPE",
                                    "The source returned an unexpected content type.",
                                )
                            chunks = bytearray()
                            async for chunk in response.aiter_bytes():
                                chunks.extend(chunk)
                                if len(chunks) > self.settings.max_bytes:
                                    raise ApiError(
                                        502,
                                        "SOURCE_TOO_LARGE",
                                        "The source response exceeded the size limit.",
                                    )
                            try:
                                # The captured site declares UTF-8; relying on HTTP defaults corrupts £.
                                body = bytes(chunks).decode("utf-8")
                            except UnicodeDecodeError as exc:
                                raise ApiError(
                                    502, "SOURCE_ENCODING", "The source text is not valid UTF-8."
                                ) from exc
                            return status, body
            except (httpx.TimeoutException, TimeoutError) as exc:
                if attempt == self.settings.retries:
                    raise ApiError(
                        504, "UPSTREAM_TIMEOUT", "The source did not respond within the timeout."
                    ) from exc
            except httpx.RequestError as exc:
                if attempt == self.settings.retries:
                    raise ApiError(502, "UPSTREAM_NETWORK_ERROR", "The source could not be reached.") from exc
            await asyncio.sleep(delay)
        raise RuntimeError("Unreachable retry state")
