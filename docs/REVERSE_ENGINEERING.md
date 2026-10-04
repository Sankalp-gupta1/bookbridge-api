# Reverse-engineering observations

Inspected on 3 October 2026 using public GET requests. The implementation was derived from the rendered HTML structure and captured source; it does not use third-party scraping APIs.

## Surface and navigation

| Observed surface | Observed URL pattern | Resulting API |
| --- | --- | --- |
| Catalogue | `/` and `/catalogue/page-2.html` | `GET /v1/books?page=N` |
| Category navigation | `/catalogue/category/books/travel_2/index.html` | `GET /v1/categories` and category-filtered book list |
| Product detail | `/catalogue/a-light-in-the-attic_1000/index.html` | `GET /v1/books/{book_id}` |
| No title-search form on inspected catalogue pages | No corresponding search endpoint observed | Bounded wrapper-side search over listing pages |

The captured catalogue reports 1,000 books, 50 pages and at most 20 books per page. Travel contains 11 items; Poetry contains 19. These are observed fixture facts, not hard-coded response counts. The parser reads and checks each page's own count.

## Mapping evidence

| HTML evidence | Parsed representation | Reason |
| --- | --- | --- |
| `.side_categories ul ul a` | Category ID, name, original URL | IDs come from actual navigation rather than a manually invented list. |
| `article.product_pod` | A summary record | One product card per listing record. |
| `h3 a[title]` | Full title | The visible text is truncated; the `title` attribute preserves the complete value. |
| `.price_color` | Exact GBP decimal string | Explicit UTF-8 decoding preserves `£`; decimal arithmetic avoids float rounding. |
| `.star-rating.Three` | Integer rating 3 | Rating is encoded as a CSS class; unfamiliar classes are rejected. |
| `.availability` | Boolean stock observation | Detail pages additionally expose the numeric stock count. |
| `li.current` and result count | Current page, total pages and item count | Next/previous API page numbers follow validated source pagination. |
| Detail `table.table-striped` | UPC, tax breakdown, availability, reviews | Table labels are checked rather than relying on row positions. |
| `ul.breadcrumb` | Product category | Category is not available from every listing card. |
| `#product_description` followed by a paragraph | Optional description | Missing optional description becomes `null`; missing required fields fail. |

Relative links differ between the root page, catalogue pages and category pages. They are resolved against the actual page URL, then checked for HTTPS, the exact source hostname and the expected path shape. A surprising link fails parsing and is never followed. `/robots.txt` returned a genuine HTTP 404 during capture; runtime checks the policy again and distinguishes a missing file from denied or unavailable access.

## Design choices

FastAPI provides input validation and an executable OpenAPI contract. HTTPX handles bounded asynchronous GETs; Beautiful Soup is sufficient because this source does not require JavaScript. A browser automation dependency or LLM parser would add latency and new failure modes without a benefit here.

The HTML parser has no network access. The fetcher knows one origin and narrow path patterns. The service composes those two pieces into list/get/search operations. Tests can therefore mutate HTML or simulate network failures independently, while the demo still exercises an actual HTTP server end to end.

Search remains a small, explicit scan instead of downloading all 1,000 products for every user query. It costs at most five listing-page fetches, plus a robots check when needed, before cache hits and bounded retries are considered. No detail-page crawl is needed for title search. The response says exactly what was covered.

This adapter addresses a narrow integration problem: an agent or internal tool needs structured catalogue reads from a website without a documented first-party API. It intentionally does not build unrelated UI, payment flows or an AI agent to satisfy a different assignment option.

## Primary references

- [Books to Scrape catalogue](https://books.toscrape.com/)
- [Publisher's description of the scraping sandbox](https://sites.toscrape.com/)
- [Observed product detail](https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html)
- [FastAPI lifespan and testing](https://fastapi.tiangolo.com/advanced/testing-events/)
- [HTTPX transport and mock-transport documentation](https://www.python-httpx.org/advanced/transports/)

The public HTML fixtures preserve source provenance. They are not authored product descriptions or real customer records.
