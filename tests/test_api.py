import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.source import CatalogueSource, Settings


def test_liveness_identifies_fixture_mode_without_claiming_upstream_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "fixture"
    assert response.json()["upstream_checked"] is False


def test_list_cache_and_no_float_money(client):
    first = client.get("/v1/books")
    second = client.get("/v1/books")
    assert first.status_code == 200
    assert first.json()["source"]["cache_hit"] is False
    assert second.json()["source"]["cache_hit"] is True
    assert first.json()["source"]["fetched_at"] == second.json()["source"]["fetched_at"]
    assert first.json()["items"][0]["price"]["amount"] == "51.77"
    assert first.json()["next_page"] == 2
    assert first.json()["previous_page"] is None
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


def test_categories_and_detail(client):
    assert len(client.get("/v1/categories").json()["items"]) == 50
    result = client.get("/v1/books/a-light-in-the-attic_1000").json()
    assert result["item"]["stock_count"] == 22
    assert result["item"]["upc"] == "a897fe39b1053632"


def test_category_and_last_page(client):
    travel = client.get("/v1/books", params={"category": "travel_2"}).json()
    assert travel["total_items"] == 11 and travel["next_page"] is None
    last = client.get("/v1/books", params={"page": 50}).json()
    assert last["previous_page"] == 49 and last["next_page"] is None


def test_partial_search_is_explicit_and_case_insensitive(client):
    data = client.get("/v1/search", params={"q": "  LIGHT in the ATTIC  ", "max_pages": 2}).json()
    assert data["matched_in_scan"] == 1
    assert data["items"][0]["id"] == "a-light-in-the-attic_1000"
    assert data["complete"] is False
    assert data["scanned_pages"] == 2 and data["next_page"] == 3
    assert data["total_source_pages"] == 50


def test_complete_search_in_single_page_category_and_no_matches(client):
    data = client.get("/v1/search", params={"q": "no-such-title-xyz", "category": "travel_2"}).json()
    assert data["complete"] is True
    assert data["items"] == [] and data["next_page"] is None
    assert data["scanned_pages"] == 1


def test_search_starting_at_last_page_does_not_claim_full_catalogue(client):
    data = client.get("/v1/search", params={"q": "the", "start_page": 50}).json()
    assert data["complete"] is False and data["next_page"] is None
    assert data["scanned_pages"] == 1


@pytest.mark.parametrize(
    "path,params",
    [
        ("/v1/books", {"page": 0}),
        ("/v1/books", {"page": -1}),
        ("/v1/books", {"page": 1001}),
        ("/v1/books", {"page": "abc"}),
        ("/v1/books", {"category": "../../etc/passwd"}),
        ("/v1/books", {"category": "https://localhost/"}),
        ("/v1/books/not-valid", {}),
        ("/v1/search", {}),
        ("/v1/search", {"q": " "}),
        ("/v1/search", {"q": "abc\nxyz"}),
        ("/v1/search", {"q": "a" * 101}),
        ("/v1/search", {"q": "x", "max_pages": 6}),
        ("/v1/search", {"q": "x", "start_page": 0}),
    ],
)
def test_invalid_inputs_share_a_safe_error_contract(client, path, params):
    result = client.get(path, params=params)
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "INVALID_INPUT"


def test_unrecorded_fixture_page_is_not_fabricated_as_real_not_found(client):
    result = client.get("/v1/books", params={"page": 3})
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "FIXTURE_NOT_RECORDED"


def test_valid_missing_book_is_404_from_source():
    source = CatalogueSource(
        Settings(min_interval=0), httpx.MockTransport(lambda request: httpx.Response(404))
    )
    with TestClient(create_app(source=source)) as client:
        response = client.get("/v1/books/not-a-real-book_999999")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


def test_rate_limit_has_retry_after():
    with TestClient(
        create_app(Settings(mode="fixture", min_interval=0, api_requests_per_minute=1))
    ) as client:
        assert client.get("/v1/books").status_code == 200
        response = client.get("/v1/categories")
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "60"
        assert client.get("/health").status_code == 200


def test_source_drift_is_a_502_not_an_empty_catalogue():
    def handler(request):
        return (
            httpx.Response(404)
            if request.url.path == "/robots.txt"
            else httpx.Response(200, text="<h1>New layout</h1>", headers={"content-type": "text/html"})
        )

    source = CatalogueSource(Settings(min_interval=0), httpx.MockTransport(handler))
    with TestClient(create_app(source=source)) as client:
        result = client.get("/v1/books")
        assert result.status_code == 502
        assert result.json()["error"]["code"] == "SOURCE_CHANGED"


def test_openapi_contains_all_public_operations(client):
    schema = client.get("/openapi.json").json()
    assert {"/health", "/v1/books", "/v1/books/{book_id}", "/v1/categories", "/v1/search"} <= schema[
        "paths"
    ].keys()
    assert "SearchResult" in schema["components"]["schemas"]


def test_invalid_mode_is_rejected():
    with pytest.raises(ValueError):
        create_app(Settings(mode="typo"))


def test_request_deadline_cancels_upstream_work():
    cancelled = False

    async def handler(request):
        nonlocal cancelled
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        try:
            await asyncio.sleep(2)
        except asyncio.CancelledError:
            cancelled = True
            raise
        return httpx.Response(200, text="late", headers={"content-type": "text/html"})

    settings = Settings(min_interval=0, request_timeout=0.03)
    source = CatalogueSource(settings, httpx.MockTransport(handler))
    with TestClient(create_app(settings, source)) as client:
        started = time.monotonic()
        response = client.get("/v1/books")
        assert response.status_code == 504
        assert response.json()["error"]["code"] == "REQUEST_TIMEOUT"
        assert cancelled and time.monotonic() - started < 1
