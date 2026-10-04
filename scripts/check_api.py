"""Exercise the real HTTP interface; exit nonzero if any contract check fails."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx


def check_api(base_url: str, expected_mode: str | None = None) -> dict:
    checks = []
    samples = {}
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=50) as client:

        def check(name, path, expected=200, params=None, predicate=None):
            response = client.get(path, params=params)
            data = response.json()
            assert response.status_code == expected, (
                f"{name}: expected {expected}, got {response.status_code}: {data}"
            )
            assert "X-Request-ID" in response.headers, f"{name}: missing request ID"
            if predicate:
                assert predicate(data), f"{name}: response contract failed"
            checks.append({"case": name, "status": "pass", "http_status": response.status_code})
            print(f"PASS  {name} [{response.status_code}]")
            return data

        health = check(
            "process health", "/health", predicate=lambda d: d["status"] == "ok" and not d["upstream_checked"]
        )
        mode = health["mode"]
        if expected_mode:
            assert mode == expected_mode, f"Expected {expected_mode} mode, got {mode}"
        samples["list"] = check(
            "first page and exact GBP price",
            "/v1/books",
            predicate=lambda d: (
                len(d["items"]) == 20
                and d["page"] == 1
                and d["items"][0]["price"]["currency"] == "GBP"
                and isinstance(d["items"][0]["price"]["amount"], str)
            ),
        )
        check("repeat request uses cache", "/v1/books", predicate=lambda d: d["source"]["cache_hit"])
        check(
            "second page",
            "/v1/books",
            params={"page": 2},
            predicate=lambda d: d["page"] == 2 and d["previous_page"] == 1,
        )
        last_number = samples["list"]["total_pages"]
        check(
            "last page has no next page",
            "/v1/books",
            params={"page": last_number},
            predicate=lambda d: d["next_page"] is None,
        )
        categories = check(
            "category list",
            "/v1/categories",
            predicate=lambda d: any(c["id"] == "travel_2" for c in d["items"]),
        )
        check(
            "category filtering",
            "/v1/books",
            params={"category": "travel_2"},
            predicate=lambda d: d["total_items"] > 0 and d["next_page"] is None,
        )
        first_book = samples["list"]["items"][0]
        samples["detail"] = check(
            "book detail and stock",
            "/v1/books/" + first_book["id"],
            predicate=lambda d: d["item"]["title"] == first_book["title"] and d["item"]["stock_count"] >= 0,
        )
        samples["search"] = check(
            "partial title search reports coverage",
            "/v1/search",
            params={"q": first_book["title"].upper(), "max_pages": 2},
            predicate=lambda d: (
                any(b["id"] == first_book["id"] for b in d["items"])
                and d["complete"] is False
                and d["next_page"] == 3
            ),
        )
        check(
            "complete category search with no matches",
            "/v1/search",
            params={"q": "zz-no-such-book-zz", "category": "travel_2"},
            predicate=lambda d: d["items"] == [] and d["complete"] is True,
        )
        check(
            "invalid page",
            "/v1/books",
            expected=422,
            params={"page": 0},
            predicate=lambda d: d["error"]["code"] == "INVALID_INPUT",
        )
        check("blank query", "/v1/search", expected=422, params={"q": " "})
        check("search budget enforced", "/v1/search", expected=422, params={"q": "book", "max_pages": 6})
        check("arbitrary URL rejected", "/v1/books", expected=422, params={"category": "http://127.0.0.1/"})
        if mode == "live":
            check(
                "missing public book",
                "/v1/books/bookbridge-nonexistent_999999999",
                expected=404,
                predicate=lambda d: d["error"]["code"] == "NOT_FOUND",
            )
        else:
            check(
                "unrecorded fixture is explicit",
                "/v1/books",
                expected=503,
                params={"page": 3},
                predicate=lambda d: d["error"]["code"] == "FIXTURE_NOT_RECORDED",
            )
        check("OpenAPI published", "/openapi.json", predicate=lambda d: "/v1/search" in d["paths"])
    return {
        "tested_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "status": "pass",
        "checks_passed": len(checks),
        "observed_category_count": len(categories["items"]),
        "checks": checks,
        "samples": samples,
    }


def save_report(report: dict, output: str | None):
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{report['checks_passed']} HTTP checks passed ({report['mode']} mode).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--expected-mode", choices=["live", "fixture"])
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        save_report(check_api(args.base_url, args.expected_mode), args.output)
    except (AssertionError, httpx.HTTPError, ValueError, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
