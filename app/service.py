import unicodedata

from app import parser
from app.errors import SourceChanged
from app.models import BookPage, BookResult, CategoryList, SearchResult
from app.source import CatalogueSource


class CatalogueService:
    def __init__(self, source: CatalogueSource):
        self.source = source

    async def categories(self) -> CategoryList:
        page = await self.source.get("/")
        try:
            return CategoryList(
                items=parser.categories(page.html, page.source.source_url), source=page.source
            )
        except SourceChanged:
            self.source.invalidate("/")
            raise

    async def books(self, number: int, category: str | None = None) -> BookPage:
        if category:
            suffix = "index.html" if number == 1 else f"page-{number}.html"
            path = f"/catalogue/category/books/{category}/{suffix}"
        else:
            path = "/" if number == 1 else f"/catalogue/page-{number}.html"
        page = await self.source.get(path)
        try:
            items, current, total_pages, total_items = parser.listing(page.html, page.source.source_url)
            if current != number:
                raise SourceChanged("The upstream returned a different page from the one requested.")
        except SourceChanged:
            self.source.invalidate(path)
            raise
        return BookPage(
            items=items,
            page=current,
            total_pages=total_pages,
            total_items=total_items,
            next_page=current + 1 if current < total_pages else None,
            previous_page=current - 1 if current > 1 else None,
            source=page.source,
        )

    async def book(self, book_id: str) -> BookResult:
        path = f"/catalogue/{book_id}/index.html"
        page = await self.source.get(path)
        try:
            book = parser.detail(page.html, page.source.source_url)
        except SourceChanged:
            self.source.invalidate(path)
            raise
        return BookResult(item=book, source=page.source)

    async def search(self, query: str, start_page: int, max_pages: int, category: str | None) -> SearchResult:
        needle = unicodedata.normalize("NFKC", query).casefold()
        matches, sources, seen = [], [], set()
        total_pages, next_page = 0, None
        for number in range(start_page, start_page + max_pages):
            page = await self.books(number, category)
            total_pages, next_page = page.total_pages, page.next_page
            sources.append(page.source)
            for book in page.items:
                if needle in unicodedata.normalize("NFKC", book.title).casefold() and book.id not in seen:
                    seen.add(book.id)
                    matches.append(book)
            if next_page is None:
                break
        return SearchResult(
            query=query,
            items=matches,
            matched_in_scan=len(matches),
            start_page=start_page,
            scanned_pages=len(sources),
            total_source_pages=total_pages,
            next_page=next_page,
            complete=start_page == 1 and next_page is None,
            sources=sources,
        )
