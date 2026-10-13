# BookBridge

BookBridge is a small **FastAPI + web dashboard** project that turns a public bookstore HTML catalogue into a clean, typed, read-only API.

The project was originally built for a Forward-Deployed Engineer assignment. I later added a production web interface so a reviewer can use the API without opening Swagger or writing curl commands.

## Live app

**https://bookbridge-api.vercel.app/**

Useful links:

- Web dashboard: https://bookbridge-api.vercel.app/
- API health: https://bookbridge-api.vercel.app/health
- Swagger docs: https://bookbridge-api.vercel.app/docs
- OpenAPI JSON: https://bookbridge-api.vercel.app/openapi.json

The public deployment runs in **fixture mode**. That is intentional.

Fixture mode uses captured HTML stored inside this repository. It gives a stable demo without repeatedly requesting the public source website.

No API key, database, account or paid service is required.

## What problem does it solve?

The source bookstore exposes normal HTML pages.

A developer who wants structured data would otherwise need to:

1. request the page,
2. understand the HTML,
3. extract book values,
4. handle pagination,
5. normalize prices and ratings,
6. repeat the same parsing logic in every client.

BookBridge moves that work into one API.

A client can simply ask for:

- books,
- categories,
- one book,
- or a title search.

## What you can do in the live dashboard

The dashboard lets you:

- browse the first captured catalogue pages,
- filter by captured categories,
- search book titles,
- see price, rating and stock status,
- open book information,
- jump to Swagger and OpenAPI documentation.

The public UI is designed around the fixture set, so it does not show broken pagination into pages that were not captured.

One complete book-detail page is included in the fixture set for **A Light in the Attic**. Other cards still show the list-page information that was actually captured.

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check that the API process is running |
| GET | `/v1/categories` | List categories |
| GET | `/v1/books?page=1` | Get one catalogue page |
| GET | `/v1/books/{book_id}` | Get full details for one book |
| GET | `/v1/search?q=light` | Search titles over a bounded number of pages |
| GET | `/docs` | Swagger UI |
| GET | `/openapi.json` | Machine-readable OpenAPI contract |

## Example requests

### List books

```bash
curl "https://bookbridge-api.vercel.app/v1/books?page=1"
```

### List categories

```bash
curl "https://bookbridge-api.vercel.app/v1/categories"
```

### Get the captured example book

```bash
curl "https://bookbridge-api.vercel.app/v1/books/a-light-in-the-attic_1000"
```

### Search titles

```bash
curl "https://bookbridge-api.vercel.app/v1/search?q=light&max_pages=2"
```

## Why the public deployment uses fixture mode

The project also has a **live mode** that reads the public practice catalogue.

For a portfolio deployment, fixture mode is better because:

- the demo is repeatable,
- it does not depend on the source website being available,
- it avoids unnecessary automated requests,
- reviewers get the same result every time,
- no hidden fallback makes a failed live request look successful.

The same parser, service layer, models and HTTP routes are used. Only the source transport changes.

## Fixture pages included

The repository contains captured examples for:

- catalogue page 1,
- catalogue page 2,
- catalogue page 50,
- one complete book-detail page,
- Poetry category,
- Travel category,
- the source site's observed `robots.txt` response.

The fixture manifest records the original path, capture time, status and SHA-256 digest.

## Data contract decisions

### Money

Money is returned as a decimal string.

Example:

```json
{
  "amount": "51.77",
  "currency": "GBP"
}
```

It is not converted to a floating-point value.

### Search

Search is intentionally bounded.

You can choose:

- `start_page`
- `max_pages` from 1 to 5
- optional category

The response says how many pages were scanned and whether the scan was complete.

### Source metadata

Responses include source information such as:

- source URL,
- fetch/capture time,
- current mode,
- cache status.

## Safety and reliability rules

The live source adapter is intentionally limited.

It:

- uses a fixed source origin,
- refuses arbitrary user-supplied URLs,
- checks the source robots policy,
- refuses unexpected redirects,
- has response-size limits,
- has timeouts,
- uses bounded retries,
- uses request pacing,
- uses a small LRU cache,
- returns explicit errors instead of silently inventing data.

## Error responses

Application errors use a consistent shape:

```json
{
  "error": {
    "code": "INVALID_INPUT",
    "message": "..."
  }
}
```

Common status codes:

| Status | Meaning |
|---:|---|
| 404 | Requested source item was not found |
| 422 | Invalid path or query input |
| 429 | Demo request limit reached |
| 502 | Unexpected source response or parser/source failure |
| 503 | Source/fixture data is unavailable for that request |
| 504 | Request time budget exceeded |

Each response also gets an `X-Request-ID`.

## Technology

### Backend

- Python 3.12
- FastAPI
- Pydantic
- HTTPX
- BeautifulSoup
- Uvicorn

### Frontend

- HTML
- CSS
- Vanilla JavaScript

### Deployment

- Vercel
- Vercel Python runtime
- `BOOKBRIDGE_MODE=fixture` in the hosted environment

## Project structure

```text
bookbridge-api/
│
├── app/
│   ├── main.py
│   ├── models.py
│   ├── parser.py
│   ├── service.py
│   ├── source.py
│   ├── errors.py
│   └── static/
│       ├── index.html
│       ├── styles.css
│       └── app.js
│
├── api/
│   └── index.py
│
├── tests/
│   └── fixtures/
│
├── scripts/
│   ├── demo.py
│   └── check_api.py
│
├── docs/
├── evidence/
├── requirements.txt
├── vercel.json
└── README.md
```

## Run locally

Use Python 3.11 or newer. Python 3.12 is the reference version.

### Step 1 — clone

```bash
git clone https://github.com/Sankalp-gupta1/bookbridge-api.git
cd bookbridge-api
```

### Step 2 — create a virtual environment

Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

### Step 3 — choose a mode

For the deterministic local demo:

Windows PowerShell:

```powershell
$env:BOOKBRIDGE_MODE = "fixture"
```

macOS / Linux:

```bash
export BOOKBRIDGE_MODE=fixture
```

For the public practice website adapter instead:

```text
BOOKBRIDGE_MODE=live
```

Use live mode responsibly and only against the fixed practice source implemented in the project.

### Step 4 — start the API

Windows:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

macOS / Linux:

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

## Run the full test suite

Install development dependencies:

Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

macOS / Linux:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
```

Run:

```bash
python -m pytest -q
```

Static checks:

```bash
ruff check .
ruff format --check .
```

## Run the one-command fixture demo

```bash
python scripts/demo.py --mode fixture
```

The script:

1. starts a real local Uvicorn server,
2. performs the HTTP checks,
3. prints the result,
4. stops the server.

## Deployment notes

Vercel uses:

```text
api/index.py
vercel.json
```

The production environment sets:

```text
BOOKBRIDGE_MODE=fixture
```

No secret value is required for this setting.

Pushes to `main` automatically create a new deployment because the Vercel project is linked to this repository.

## What this project does not claim

BookBridge does not claim to have discovered a hidden bookstore API.

It reconstructs a useful read-only contract from the public HTML of a website specifically published for scraping practice.

It is also not a payment, ecommerce checkout or real inventory service.

## Author

**Sankalp Gupta**

- GitHub: https://github.com/Sankalp-gupta1
- LinkedIn: https://www.linkedin.com/in/sankalp-gupta-rishi-8617302b0/
