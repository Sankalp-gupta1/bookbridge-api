# BookBridge

**Razorpay Forward-Deployed Engineer, Agent Studio — Assignment 1: Reverse-engineer an API**

BookBridge turns the public HTML catalogue at [Books to Scrape](https://books.toscrape.com/) into a small, typed, read-only API. A consumer can list books, inspect a product, browse categories and search titles without understanding the website's HTML.

The site is a fictional bookstore published for scraping practice. No documented first-party public API was found on the inspected site or its [publisher's sandbox page](https://sites.toscrape.com/). This project reconstructs a contract from the HTML; it does not claim to have discovered a hidden API. Third-party wrappers may exist. Prices and ratings on the source are randomly assigned and are not real market data.

## Run the complete demonstration

Use **Python 3.12** (tested). The code requires Python 3.11 or newer. No API key, account, database or paid service is needed. Clone the repository and run commands from its root:

```bash
git clone https://github.com/Sankalp-gupta1/bookbridge-api.git
cd bookbridge-api
```

If using the submission ZIP instead, run commands from its extracted `bookbridge` directory.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/demo.py --mode fixture
.\.venv\Scripts\python.exe -m pytest -q
```

No PowerShell activation-policy change is needed; these commands invoke the environment's Python directly.

### macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/demo.py --mode fixture
.venv/bin/python -m pytest -q
```

The demo starts a real local Uvicorn server on a free loopback port, performs **16 HTTP checks**, prints the results and stops the server. Fixture mode needs no internet after dependencies are installed. It uses captured HTML through the **same HTTP fetcher, parser, service and API** as live mode; only the upstream transport is replaced.

### Live website demonstration

```bash
python scripts/demo.py --mode live --output evidence/live-smoke.json
```

Use your virtual environment's Python in the command above. This makes a small number of public GET requests, paced at a maximum of one start per second per process. It checks the real source, including a genuine missing-book response. A failure exits nonzero; it never switches to fixtures silently.

## Explore the API

Start a server with the virtual environment's Python:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Then open **http://127.0.0.1:8000/docs** for Swagger UI or **http://127.0.0.1:8000/openapi.json** for the machine-readable contract. The default is **live mode**. To use fixtures instead:

```powershell
# PowerShell, before starting Uvicorn
$env:BOOKBRIDGE_MODE = "fixture"
```

```bash
# macOS / Linux, before starting Uvicorn
export BOOKBRIDGE_MODE=fixture
```

The `.env.example` file documents the one setting; `.env` files are not automatically loaded. Swagger UI loads its assets from a CDN. Offline JSON endpoints and the test script do not depend on that CDN.

| Method and endpoint | Behaviour |
| --- | --- |
| `GET /health` | Process liveness and mode; explicitly does not claim upstream health. |
| `GET /v1/categories` | Category IDs, names and original URLs. |
| `GET /v1/books?page=2` | One source page, up to 20 books; total count and pagination. |
| `GET /v1/books?category=travel_2` | Books from one category. |
| `GET /v1/books/a-light-in-the-attic_1000` | Title, UPC, description, category, price/tax, rating and stock count. |
| `GET /v1/search?q=light&max_pages=2` | Case-insensitive title search with explicit coverage. |

Examples:

```bash
curl "http://127.0.0.1:8000/v1/books?page=1"
curl "http://127.0.0.1:8000/v1/books/a-light-in-the-attic_1000"
curl "http://127.0.0.1:8000/v1/search?q=light&max_pages=2"
python scripts/check_api.py --base-url http://127.0.0.1:8000 --expected-mode live
```

For PowerShell, use `curl.exe` if `curl` is mapped to another command.

## Contract decisions

- Money is a decimal **string**, such as `{"amount":"51.77","currency":"GBP"}`. It is not a floating-point approximation.
- Every result carries `source_url`, `fetched_at`, `mode` and `cache_hit`. Fixture timestamps refer to capture time, not the time of the API call.
- IDs are the observed source URL slugs. A UPC is available on detail pages; the wrapper does not invent a UPC for list results.
- Search accepts `q`, optional `category`, `start_page` and `max_pages` (1–5, default 3). It matches titles only, preserving source order. `matched_in_scan` is not a catalogue-wide count.
- `complete=true` means that this call started at page 1 and reached the final page of the selected catalogue/category. Otherwise use `next_page` to continue. Starting at the last page never implies a complete catalogue search.
- Failed searches return an error instead of a silently truncated success. Independent page reads are not a transactional snapshot.

## Reliability and boundaries

The fetcher checks `robots.txt`, uses a descriptive user agent, follows no redirects, accepts only fixed catalogue paths on the HTTPS source origin and refuses login/access-denied responses. It does not execute source JavaScript, log in, solve challenges or accept user-supplied URLs.

Successful HTML is cached for five minutes in a 32-entry LRU. Concurrent misses are serialized; identical requests reuse the first response. Each attempt has an eight-second deadline and a two-megabyte decoded-response limit. Transient failures get at most two retries with exponential backoff. `Retry-After` cooldowns persist even if the initiating caller cancels. A route has a 45-second total budget that cancels actual upstream work.

The local demo API allows 60 `/v1/` requests per minute per process. Source pacing, cache and rate limits are **not shared across workers**. Use one worker. There is no public deployment authentication in this assignment; keep the server on loopback. A production gateway, shared limits and an authorized data source are needed before exposing it to users.

| Status | Meaning |
| --- | --- |
| `404` | The upstream says the requested book/page does not exist. |
| `422` | Invalid input, such as page 0, an empty query or an arbitrary URL. |
| `429` | This API's local request budget was reached. |
| `502` | Source HTML drift, access denial, unexpected redirect, invalid content or network failure. |
| `503` | Source busy/cooldown, robots disallow or a page missing from the fixture set. |
| `504` | Upstream attempt or total request deadline exceeded. |

Errors from these application paths have `{"error":{"code":"...","message":"..."}}`. `Retry-After` is returned when appropriate. Every HTTP response includes an `X-Request-ID`.

## Validation and evidence

```bash
python -m pytest -q --junitxml=evidence/pytest.xml
ruff check .
ruff format --check .
python scripts/demo.py --mode fixture --output evidence/fixture-smoke.json
python scripts/demo.py --mode live --output evidence/live-smoke.json
```

See [the verification record](docs/VERIFICATION.md) and the machine-readable files in `evidence/`. Offline tests cover parser drift, real captured pagination, invalid input, 404s, cache expiry/eviction, concurrent calls, robots denial, redirects, retries, cooldown cancellation, response size, encoding and request cancellation. Live smoke checks are deliberately separate from deterministic tests.

The [fixture manifest](tests/fixtures/manifest.json) records original paths, HTTP status, capture time and SHA-256 digests. Captures include the first, second and last catalogue pages, two categories, one detail page and the actual `robots.txt` 404. Other fixture pages return `FIXTURE_NOT_RECORDED`, not fabricated source data.

## Design and handover

| File | Responsibility |
| --- | --- |
| `app/main.py` | HTTP validation, routes, request budget, error contract, lifespan. |
| `app/source.py` | Allowed source paths, robots policy, HTTP retries, pacing, bounded cache. |
| `app/parser.py` | Pure HTML parsing and contract checks. |
| `app/service.py` | Catalogue operations and bounded search. |
| `app/models.py` | Typed response models and OpenAPI schemas. |
| `scripts/demo.py` | One-command server + HTTP test + shutdown. |
| `scripts/check_api.py` | Test an already-running API. |

Read [reverse-engineering observations](docs/REVERSE_ENGINEERING.md) and the [short limitations and long-term fix note](docs/LIMITATIONS.md). [AI assistance](docs/AI_ASSISTANCE.md) is disclosed separately. This is assignment option 1; it does not claim to be an Agent Studio connector, an MCP server or a production merchant deployment.

### Optional container

```bash
docker build -t bookbridge .
docker run --rm -p 127.0.0.1:8000:8000 bookbridge
```

The Dockerfile uses a non-root user and pinned Python dependencies. Docker execution is not included in the recorded validation because Docker was unavailable in the build environment. The [GitHub Actions workflow passed on 4 October 2026](https://github.com/Sankalp-gupta1/bookbridge-api/actions/runs/37183612280), including lint, formatting, tests and the fixture HTTP demo.
