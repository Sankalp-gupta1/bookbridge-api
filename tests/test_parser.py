import hashlib
import json

import pytest

from app import parser
from app.errors import SourceChanged


def test_real_capture_has_1000_books_and_full_titles(html):
    books, page, pages, total = parser.listing(html, parser.ORIGIN + "/")
    assert (len(books), page, pages, total) == (20, 1, 50, 1000)
    assert books[0].title == "A Light in the Attic"
    assert books[0].price.model_dump() == {"amount": "51.77", "currency": "GBP"}
    assert books[0].rating == 3
    assert books[0].source_url == parser.ORIGIN + "/catalogue/a-light-in-the-attic_1000/index.html"
    assert "..." not in books[4].title  # The displayed card label is truncated, the title attribute is not.


def test_categories_are_extracted_from_navigation(html):
    values = parser.categories(html, parser.ORIGIN + "/")
    assert len(values) == 50
    assert next(c for c in values if c.id == "poetry_23").name == "Poetry"


@pytest.mark.parametrize(
    "file,path,expected",
    [
        ("page2.html", "/catalogue/page-2.html", (20, 2, 50, 1000)),
        ("page50.html", "/catalogue/page-50.html", (20, 50, 50, 1000)),
        ("poetry.html", "/catalogue/category/books/poetry_23/index.html", (19, 1, 1, 19)),
        ("travel.html", "/catalogue/category/books/travel_2/index.html", (11, 1, 1, 11)),
    ],
)
def test_real_pagination(fixture_dir, file, path, expected):
    books, page, pages, total = parser.listing((fixture_dir / file).read_text(), parser.ORIGIN + path)
    assert (len(books), page, pages, total) == expected
    assert all("/catalogue/catalogue/" not in b.source_url for b in books)


def test_detail_with_upc_stock_category_and_exact_money(fixture_dir):
    book = parser.detail(
        (fixture_dir / "book.html").read_text(),
        parser.ORIGIN + "/catalogue/a-light-in-the-attic_1000/index.html",
    )
    assert book.upc == "a897fe39b1053632"
    assert book.stock_count == 22 and book.in_stock
    assert book.category.id == "poetry_23"
    assert book.tax.amount == "0.00" and book.review_count == 0
    assert book.description and "Shel Silverstein" in book.description


@pytest.mark.parametrize(
    "old,new",
    [
        ('class="price_color"', 'class="price_v2"'),
        ("£51.77", "$51.77"),
        ("star-rating Three", "star-rating Unknown"),
        ("Page 1 of 50", "Page one of fifty"),
        ('title="A Light in the Attic"', 'title=""'),
        ("In stock", "Maybe in stock"),
        ("<strong>1000</strong>", "<strong>900</strong>"),
    ],
)
def test_source_drift_fails_loudly(html, old, new):
    assert old in html
    with pytest.raises(SourceChanged):
        parser.listing(html.replace(old, new), parser.ORIGIN + "/")


def test_no_silent_success_on_block_page():
    with pytest.raises(SourceChanged):
        parser.listing("<html><h1>Access denied</h1></html>", parser.ORIGIN + "/")


@pytest.mark.parametrize(
    "href",
    [
        "https://evil.example/catalogue/book_1/index.html",
        "http://books.toscrape.com/catalogue/book_1/index.html",
        "https://books.toscrape.com.evil.example/catalogue/book_1/index.html",
        "https://books.toscrape.com/catalogue/book_1/index.html?secret=1",
        "file:///etc/passwd",
        "//127.0.0.1/admin",
    ],
)
def test_hostile_source_links_are_rejected(href):
    with pytest.raises(SourceChanged):
        parser.canonical_link(parser.ORIGIN + "/", href, "book")


def test_missing_required_detail_field_fails(fixture_dir):
    html = (fixture_dir / "book.html").read_text().replace("<th>UPC</th>", "<th>Product code</th>")
    with pytest.raises(SourceChanged):
        parser.detail(html, parser.ORIGIN + "/catalogue/a-light-in-the-attic_1000/index.html")


def test_inconsistent_detail_price_fails(fixture_dir):
    html = (fixture_dir / "book.html").read_text().replace("£51.77", "£51.78", 1)
    with pytest.raises(SourceChanged):
        parser.detail(html, parser.ORIGIN + "/catalogue/a-light-in-the-attic_1000/index.html")


def test_fixture_checksums_match_provenance(fixture_dir):
    manifest = json.loads((fixture_dir / "manifest.json").read_text())
    assert manifest["origin"] == parser.ORIGIN
    for name, info in manifest["files"].items():
        assert hashlib.sha256((fixture_dir / name).read_bytes()).hexdigest() == info["sha256"]
