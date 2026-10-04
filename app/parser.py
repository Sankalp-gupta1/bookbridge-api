"""Pure HTML parsing. No network calls, JavaScript execution, or silent defaults."""

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from app.errors import SourceChanged
from app.models import Book, BookSummary, Category, Price

ORIGIN = "https://books.toscrape.com"
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*_[1-9][0-9]*"
BOOK_PATH = re.compile(rf"^/catalogue/({SLUG})/index\.html$")
CATEGORY_PATH = re.compile(rf"^/catalogue/category/books/({SLUG})/index\.html$")
RATINGS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


def required(node: BeautifulSoup | Tag, selector: str) -> Tag:
    result = node.select_one(selector)
    if not isinstance(result, Tag):
        raise SourceChanged(f"A required HTML element is missing: {selector}.")
    return result


def text(node: Tag) -> str:
    return " ".join(node.stripped_strings)


def canonical_link(base: str, href: str, kind: str) -> tuple[str, str]:
    url = urljoin(base, href)
    parts = urlsplit(url)
    pattern = BOOK_PATH if kind == "book" else CATEGORY_PATH
    match = pattern.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc != "books.toscrape.com"
        or parts.query
        or parts.fragment
        or not match
    ):
        raise SourceChanged("The source contains an unexpected catalogue link.")
    return match.group(1), url


def price(value: str) -> Price:
    if not re.fullmatch(r"£\d+\.\d{2}", value.strip()):
        raise SourceChanged("A price has an unexpected currency or format.")
    try:
        amount = Decimal(value.strip()[1:])
    except InvalidOperation as exc:
        raise SourceChanged("A price could not be parsed.") from exc
    return Price(amount=format(amount, ".2f"))


def rating(node: Tag) -> int:
    classes = required(node, ".star-rating").get("class", [])
    values = [RATINGS[c] for c in classes if c in RATINGS]
    if len(values) != 1:
        raise SourceChanged("A book rating is missing or ambiguous.")
    return values[0]


def availability(value: str) -> tuple[bool, int | None]:
    match = re.fullmatch(r"In stock(?: \((\d+) available\))?", value)
    if match:
        return True, int(match.group(1)) if match.group(1) is not None else None
    if value == "Out of stock":
        return False, 0
    raise SourceChanged("A stock status has an unexpected format.")


def categories(html: str, url: str) -> list[Category]:
    soup = BeautifulSoup(html, "html.parser")
    nodes = required(soup, ".side_categories").select("ul ul a[href]")
    items = []
    for node in nodes:
        identifier, source_url = canonical_link(url, str(node["href"]), "category")
        name = text(node)
        if not name:
            raise SourceChanged("A category name is empty.")
        items.append(Category(id=identifier, name=name, source_url=source_url))
    if not items or len({c.id for c in items}) != len(items):
        raise SourceChanged("Category navigation is empty or contains duplicate IDs.")
    return items


def listing(html: str, url: str) -> tuple[list[BookSummary], int, int, int]:
    soup = BeautifulSoup(html, "html.parser")
    heading = text(required(soup, "h1"))
    if not heading:
        raise SourceChanged()
    count_node = required(soup, "form.form-horizontal strong")
    if not text(count_node).isdigit():
        raise SourceChanged("The catalogue count is missing.")
    total_items = int(text(count_node))
    page, total_pages = 1, 1
    pager = soup.select_one("li.current")
    if pager:
        match = re.fullmatch(r"Page (\d+) of (\d+)", text(pager))
        if not match:
            raise SourceChanged("The source pagination format changed.")
        page, total_pages = map(int, match.groups())
        if not 1 <= page <= total_pages:
            raise SourceChanged("The source pagination is inconsistent.")
    nodes = soup.select("article.product_pod")
    expected = min(20, max(0, total_items - (page - 1) * 20))
    if total_pages != max(1, (total_items + 19) // 20) or len(nodes) != expected:
        raise SourceChanged("The catalogue count does not match its cards or pagination.")
    items = []
    for node in nodes:
        link = required(node, "h3 a[href][title]")
        identifier, source_url = canonical_link(url, str(link["href"]), "book")
        title = str(link["title"]).strip()
        if not title:
            raise SourceChanged("A book title is empty.")
        in_stock, _ = availability(text(required(node, ".availability")))
        items.append(
            BookSummary(
                id=identifier,
                title=title,
                price=price(text(required(node, ".price_color"))),
                rating=rating(node),
                in_stock=in_stock,
                source_url=source_url,
            )
        )
    if len({b.id for b in items}) != len(items):
        raise SourceChanged("The source page contains duplicate book IDs.")
    return items, page, total_pages, total_items


def detail(html: str, url: str) -> Book:
    soup = BeautifulSoup(html, "html.parser")
    main = required(soup, ".product_main")
    identifier, _ = canonical_link(url, url, "book")
    title = text(required(main, "h1"))
    if not title:
        raise SourceChanged("A book title is empty.")
    fields = {}
    for row in required(soup, "table.table-striped").select("tr"):
        key, value = text(required(row, "th")), text(required(row, "td"))
        if key in fields:
            raise SourceChanged("A product information field is duplicated.")
        fields[key] = value
    needed = {"UPC", "Price (excl. tax)", "Price (incl. tax)", "Tax", "Availability", "Number of reviews"}
    if not needed <= fields.keys() or not re.fullmatch(r"[a-zA-Z0-9]+", fields["UPC"]):
        raise SourceChanged("Required product information is missing or invalid.")
    in_stock, stock = availability(fields["Availability"])
    if stock is None or (in_stock and stock == 0) or not fields["Number of reviews"].isdigit():
        raise SourceChanged("The stock quantity or review count is invalid.")
    category_links = required(soup, "ul.breadcrumb").select('a[href*="/category/books/"]')
    if len(category_links) != 1:
        raise SourceChanged("The book category breadcrumb is missing or ambiguous.")
    category_node = category_links[0]
    category_id, category_url = canonical_link(url, str(category_node["href"]), "category")
    description_heading = soup.select_one("#product_description")
    description_node = description_heading.find_next_sibling("p") if description_heading else None
    description = text(description_node) if isinstance(description_node, Tag) else None
    displayed = price(text(required(main, ".price_color")))
    inclusive = price(fields["Price (incl. tax)"])
    exclusive = price(fields["Price (excl. tax)"])
    tax = price(fields["Tax"])
    if displayed != inclusive or Decimal(exclusive.amount) + Decimal(tax.amount) != Decimal(inclusive.amount):
        raise SourceChanged("The source has inconsistent prices.")
    return Book(
        id=identifier,
        title=title,
        price=inclusive,
        rating=rating(main),
        in_stock=in_stock,
        source_url=url,
        upc=fields["UPC"],
        category=Category(id=category_id, name=text(category_node), source_url=category_url),
        description=description,
        stock_count=stock,
        price_excl_tax=exclusive,
        tax=tax,
        review_count=int(fields["Number of reviews"]),
    )
