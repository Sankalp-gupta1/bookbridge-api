import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from app.errors import ApiError
from app.source import CatalogueSource, Settings, retry_after_seconds


def response_for(request, content="<html>ok</html>"):
    return (
        httpx.Response(404)
        if request.url.path == "/robots.txt"
        else httpx.Response(200, text=content, headers={"content-type": "text/html"})
    )


async def test_parallel_cache_misses_make_only_one_catalogue_request():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return response_for(request)

    source = CatalogueSource(Settings(min_interval=0), httpx.MockTransport(handler))
    try:
        pages = await asyncio.gather(*(source.get("/") for _ in range(5)))
        assert seen == ["/robots.txt", "/"]
        assert sum(not p.source.cache_hit for p in pages) == 1
    finally:
        await source.close()


async def test_expired_cache_refetches_and_does_not_serve_stale():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return response_for(request)

    source = CatalogueSource(Settings(min_interval=0, cache_ttl=0), httpx.MockTransport(handler))
    try:
        await source.get("/")
        second = await source.get("/")
        assert seen == ["/robots.txt", "/", "/"]
        assert second.source.cache_hit is False
    finally:
        await source.close()


async def test_lru_capacity_bounds_memory():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return response_for(request)

    source = CatalogueSource(Settings(min_interval=0, cache_size=1), httpx.MockTransport(handler))
    try:
        await source.get("/")
        await source.get("/catalogue/page-2.html")
        await source.get("/")
        assert seen.count("/") == 2
    finally:
        await source.close()


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.example/",
        "//localhost/",
        "/../admin",
        "/catalogue/%2e%2e/admin",
        "/?url=http://127.0.0.1",
        "/robots.txt",
        "/login",
        "/catalogue/page-0.html",
    ],
)
async def test_arbitrary_source_paths_make_no_network_calls(path):
    def handler(request):
        pytest.fail("An invalid path must never reach the HTTP transport")

    source = CatalogueSource(Settings(min_interval=0), httpx.MockTransport(handler))
    try:
        with pytest.raises(ApiError) as result:
            await source.get(path)
        assert result.value.code == "INVALID_SOURCE_PATH"
    finally:
        await source.close()


async def test_robots_disallow_prevents_fetch():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(
            200, text="User-agent: *\nDisallow: /\n", headers={"content-type": "text/plain"}
        )

    source = CatalogueSource(Settings(min_interval=0), httpx.MockTransport(handler))
    try:
        with pytest.raises(ApiError) as result:
            await source.get("/")
        assert result.value.code == "ROBOTS_DENIED"
        assert seen == ["/robots.txt"]
    finally:
        await source.close()


async def test_expired_robots_policy_is_rechecked_before_serving_cache():
    robots_calls = 0

    def handler(request):
        nonlocal robots_calls
        if request.url.path == "/robots.txt":
            robots_calls += 1
            return (
                httpx.Response(404)
                if robots_calls == 1
                else httpx.Response(
                    200, text="User-agent: *\nDisallow: /\n", headers={"content-type": "text/plain"}
                )
            )
        return response_for(request)

    source = CatalogueSource(Settings(min_interval=0, robots_ttl=0), httpx.MockTransport(handler))
    try:
        await source.get("/")
        with pytest.raises(ApiError) as result:
            await source.get("/")
        assert result.value.code == "ROBOTS_DENIED" and robots_calls == 2
    finally:
        await source.close()


@pytest.mark.parametrize("status", [401, 403])
async def test_denied_robots_is_not_treated_as_permission(status):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(status)

    source = CatalogueSource(Settings(min_interval=0), httpx.MockTransport(handler))
    try:
        with pytest.raises(ApiError) as result:
            await source.get("/")
        assert result.value.code == "SOURCE_ACCESS_DENIED"
        assert seen == ["/robots.txt"]
    finally:
        await source.close()


@pytest.mark.parametrize(
    "response,code",
    [
        (httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"}), "SOURCE_REDIRECT"),
        (httpx.Response(200, json={"changed": True}), "SOURCE_CONTENT_TYPE"),
        (httpx.Response(200, content=b"\xff", headers={"content-type": "text/html"}), "SOURCE_ENCODING"),
        (httpx.Response(403), "SOURCE_ACCESS_DENIED"),
        (httpx.Response(418), "UPSTREAM_HTTP_ERROR"),
    ],
)
async def test_unsafe_or_unexpected_responses_are_not_retried(response, code):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(404) if request.url.path == "/robots.txt" else response

    source = CatalogueSource(Settings(min_interval=0), httpx.MockTransport(handler))
    try:
        with pytest.raises(ApiError) as result:
            await source.get("/")
        assert result.value.code == code
        assert seen == ["/robots.txt", "/"]
    finally:
        await source.close()


async def test_oversized_html_is_rejected():
    source = CatalogueSource(Settings(min_interval=0, max_bytes=5), httpx.MockTransport(response_for))
    try:
        with pytest.raises(ApiError) as result:
            await source.get("/")
        assert result.value.code == "SOURCE_TOO_LARGE"
    finally:
        await source.close()


async def test_retry_after_is_honoured_and_success_can_be_retried(monkeypatch):
    calls, waits = [], []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay):
        waits.append(delay)
        await real_sleep(delay)

    monkeypatch.setattr("app.source.asyncio.sleep", fake_sleep)

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(request.url.path)
        return httpx.Response(429, headers={"Retry-After": "2"}) if len(calls) == 1 else response_for(request)

    source = CatalogueSource(Settings(min_interval=0), httpx.MockTransport(handler))
    try:
        assert (await source.get("/")).html == "<html>ok</html>"
        assert len(calls) == 2 and 2 in waits
    finally:
        await source.close()


async def test_long_retry_after_is_returned_and_blocks_new_upstream_calls():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return (
            httpx.Response(404)
            if request.url.path == "/robots.txt"
            else httpx.Response(429, headers={"Retry-After": "120"})
        )

    source = CatalogueSource(Settings(min_interval=0), httpx.MockTransport(handler))
    try:
        with pytest.raises(ApiError) as first:
            await source.get("/")
        assert first.value.status == 503 and first.value.retry_after == 120
        with pytest.raises(ApiError) as second:
            await source.get("/catalogue/page-2.html")
        assert second.value.code == "UPSTREAM_COOLDOWN"
        assert seen == ["/robots.txt", "/"]
    finally:
        await source.close()


@pytest.mark.parametrize(
    "kind,code,status",
    [
        ("server", "UPSTREAM_UNAVAILABLE", 503),
        ("timeout", "UPSTREAM_TIMEOUT", 504),
        ("network", "UPSTREAM_NETWORK_ERROR", 502),
    ],
)
async def test_retries_are_bounded(monkeypatch, kind, code, status):
    calls = []

    async def fake_sleep(delay):
        pass

    monkeypatch.setattr("app.source.asyncio.sleep", fake_sleep)

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(request.url.path)
        if kind == "server":
            return httpx.Response(503)
        if kind == "timeout":
            raise httpx.ReadTimeout("fake private connection text", request=request)
        raise httpx.ConnectError("fake private connection text", request=request)

    source = CatalogueSource(Settings(min_interval=0), httpx.MockTransport(handler))
    try:
        with pytest.raises(ApiError) as result:
            await source.get("/")
        assert result.value.code == code and result.value.status == status
        assert "private" not in result.value.message
        assert len(calls) == 3
    finally:
        await source.close()


async def test_timeout_cancels_a_slow_fetch_and_releases_the_lock():
    cancelled = False

    async def handler(request):
        nonlocal cancelled
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if not cancelled:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled = True
                raise
        return response_for(request)

    source = CatalogueSource(Settings(min_interval=0, timeout=0.01, retries=0), httpx.MockTransport(handler))
    try:
        with pytest.raises(ApiError) as result:
            await source.get("/")
        assert result.value.code == "UPSTREAM_TIMEOUT" and cancelled
        assert (await source.get("/")).html == "<html>ok</html>"
    finally:
        await source.close()


async def test_global_pacing_and_robots_crawl_delay(monkeypatch):
    waits = []

    async def fake_sleep(delay):
        waits.append(delay)

    monkeypatch.setattr("app.source.asyncio.sleep", fake_sleep)

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nAllow: /\nCrawl-delay: 3\n", headers={"content-type": "text/plain"}
            )
        return response_for(request)

    source = CatalogueSource(Settings(min_interval=1), httpx.MockTransport(handler))
    try:
        await source.get("/")
        await source.get("/catalogue/page-2.html")
        assert any(delay > 0.9 for delay in waits)
        assert any(delay > 2.9 for delay in waits)
    finally:
        await source.close()


def test_retry_after_accepts_http_dates_and_rejects_invalid_headers():
    assert retry_after_seconds("120") == 120
    future = format_datetime(datetime.now(UTC) + timedelta(seconds=30))
    assert 29 <= retry_after_seconds(future) <= 30
    assert retry_after_seconds("nonsense") is None
    assert retry_after_seconds(None) is None


async def test_cancelled_retry_preserves_upstream_cooldown():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return (
            httpx.Response(404)
            if request.url.path == "/robots.txt"
            else httpx.Response(429, headers={"Retry-After": "2"})
        )

    source = CatalogueSource(Settings(min_interval=0), httpx.MockTransport(handler))
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(source.get("/"), timeout=0.02)
        with pytest.raises(ApiError) as result:
            await source.get("/catalogue/page-2.html")
        assert result.value.code == "UPSTREAM_COOLDOWN"
        assert calls == ["/robots.txt", "/"]
    finally:
        await source.close()
