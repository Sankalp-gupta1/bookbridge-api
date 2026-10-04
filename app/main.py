import asyncio
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.routing import APIRoute

from app.errors import ApiError
from app.models import BookPage, BookResult, CategoryList, ErrorResponse, SearchResult
from app.parser import SLUG
from app.service import CatalogueService
from app.source import CatalogueSource, Settings, fixture_transport

logger = logging.getLogger("bookbridge")


def error_response(error: ApiError) -> JSONResponse:
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after is not None else {}
    return JSONResponse(
        status_code=error.status,
        content={"error": {"code": error.code, "message": error.message}},
        headers=headers,
    )


def create_app(settings: Settings | None = None, source: CatalogueSource | None = None) -> FastAPI:
    settings = settings or Settings(mode=os.getenv("BOOKBRIDGE_MODE", "live"))
    if settings.mode not in {"live", "fixture"}:
        raise ValueError("BOOKBRIDGE_MODE must be 'live' or 'fixture'.")

    class DeadlineRoute(APIRoute):
        def get_route_handler(self):
            handler = super().get_route_handler()

            async def bounded_handler(request: Request):
                # Bound the actual handler task so cancellation reaches the HTTP request
                # and releases the source lock, rather than only timing out middleware.
                try:
                    async with asyncio.timeout(settings.request_timeout):
                        return await handler(request)
                except TimeoutError as exc:
                    raise ApiError(
                        504, "REQUEST_TIMEOUT", "The total request time budget was exceeded."
                    ) from exc

            return bounded_handler

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal source
        if source is None:
            if settings.mode == "fixture":
                transport, captured_at = fixture_transport(
                    Path(__file__).resolve().parents[1] / "tests" / "fixtures"
                )
                source = CatalogueSource(settings, transport, captured_at)
            else:
                source = CatalogueSource(settings)
        app.state.service = CatalogueService(source)
        app.state.requests = deque()
        yield
        await source.close()

    app = FastAPI(
        title="BookBridge",
        version="1.0.0",
        lifespan=lifespan,
        description="Read-only APIs over the public Books to Scrape HTML catalogue. Prices and ratings are fictional. "
        "Search scans a bounded number of pages and explicitly reports completeness. No credentials are required.",
        responses={code: {"model": ErrorResponse} for code in (404, 422, 429, 502, 503, 504)},
    )
    app.router.route_class = DeadlineRoute

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return error_response(
            ApiError(
                422, "INVALID_INPUT", "Invalid path or query parameters. See /docs for supported values."
            )
        )

    @app.middleware("http")
    async def request_limits(request: Request, call_next):
        request_id, started = str(uuid4()), time.monotonic()
        if request.url.path.startswith("/v1/"):
            window = request.app.state.requests
            while window and window[0] <= started - 60:
                window.popleft()
            if len(window) >= settings.api_requests_per_minute:
                response = error_response(
                    ApiError(429, "API_RATE_LIMITED", "Demo API request limit reached.", 60)
                )
            else:
                window.append(started)
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        # Queries and HTML bodies are deliberately not logged.
        logger.info(
            "request_id=%s method=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            response.status_code,
            (time.monotonic() - started) * 1000,
        )
        return response

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/docs")

    @app.get("/health", tags=["Operations"])
    async def health():
        return {
            "status": "ok",
            "mode": settings.mode,
            "version": "1.0.0",
            "upstream_checked": False,
            "note": "Process liveness only; query /v1/books to check the source.",
        }

    @app.get("/v1/categories", response_model=CategoryList, tags=["Catalogue"])
    async def get_categories(request: Request):
        return await request.app.state.service.categories()

    @app.get("/v1/books", response_model=BookPage, tags=["Catalogue"])
    async def get_books(
        request: Request,
        page: Annotated[int, Query(ge=1, le=1000)] = 1,
        category: Annotated[str | None, Query(pattern=f"^{SLUG}$", max_length=200)] = None,
    ):
        """One upstream page (up to 20 books). Category IDs come from /v1/categories."""
        return await request.app.state.service.books(page, category)

    @app.get("/v1/books/{book_id}", response_model=BookResult, tags=["Catalogue"])
    async def get_book(
        request: Request, book_id: Annotated[str, PathParam(pattern=f"^{SLUG}$", max_length=250)]
    ):
        """Read public details, UPC, stock count, category and tax-inclusive price."""
        return await request.app.state.service.book(book_id)

    @app.get("/v1/search", response_model=SearchResult, tags=["Catalogue"])
    async def search(
        request: Request,
        q: Annotated[str, Query(min_length=1, max_length=100)],
        start_page: Annotated[int, Query(ge=1, le=1000)] = 1,
        max_pages: Annotated[int, Query(ge=1, le=5)] = 3,
        category: Annotated[str | None, Query(pattern=f"^{SLUG}$", max_length=200)] = None,
    ):
        """Case-insensitive title substring search; at most five source pages per call."""
        query = q.strip()
        if not query or any(ord(character) < 32 for character in query):
            raise ApiError(422, "INVALID_INPUT", "Search needs non-empty text without control characters.")
        return await request.app.state.service.search(query, start_page, max_pages, category)

    return app


app = create_app()
