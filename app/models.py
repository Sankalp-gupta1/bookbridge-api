from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Price(Model):
    # Decimal strings preserve money exactly, including trailing zeroes.
    amount: str = Field(pattern=r"^\d+\.\d{2}$", examples=["51.77"])
    currency: Literal["GBP"] = "GBP"


class BookSummary(Model):
    id: str
    title: str
    price: Price
    rating: int = Field(ge=1, le=5)
    in_stock: bool
    source_url: str


class Category(Model):
    id: str
    name: str
    source_url: str


class Book(BookSummary):
    upc: str
    category: Category
    description: str | None
    stock_count: int = Field(ge=0)
    price_excl_tax: Price
    tax: Price
    review_count: int = Field(ge=0)


class SourceMeta(Model):
    mode: Literal["live", "fixture"]
    source_url: str
    fetched_at: datetime
    cache_hit: bool


class BookPage(Model):
    items: list[BookSummary]
    page: int = Field(ge=1)
    total_pages: int = Field(ge=1)
    total_items: int = Field(ge=0)
    next_page: int | None
    previous_page: int | None
    source: SourceMeta


class CategoryList(Model):
    items: list[Category]
    source: SourceMeta


class BookResult(Model):
    item: Book
    source: SourceMeta


class SearchResult(Model):
    query: str
    items: list[BookSummary]
    matched_in_scan: int
    start_page: int
    scanned_pages: int
    total_source_pages: int
    next_page: int | None
    complete: bool
    sources: list[SourceMeta]
    note: str = "Title substring matches in the scanned pages only; source order is preserved."


class ErrorDetail(Model):
    code: str
    message: str


class ErrorResponse(Model):
    error: ErrorDetail
