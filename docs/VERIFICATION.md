# Verification record

Validated on **3 October 2026** with Python **3.12.14** on Linux.

| Check | Observed result | Evidence |
| --- | --- | --- |
| Deterministic test suite | **81 passed**, 0 failed, 0 skipped | `evidence/pytest.xml` |
| Fixture-mode real HTTP demo | **16 checks passed** | `evidence/fixture-smoke.json` |
| Live-source real HTTP demo | **16 checks passed** | `evidence/live-smoke.json` |
| Ruff lint | Passed | `ruff check .` |
| Ruff formatting | Passed | `ruff format --check .` |
| Dependency consistency | No broken requirements | `python -m pip check` |
| OpenAPI export | Generated from the actual FastAPI app | `docs/openapi.json` |

Live smoke completed at **2026-10-03 14:22:12 UTC**. It observed 50 categories and checked catalogue pagination, a detail record, cached responses, partial search, complete category search, invalid inputs and a genuine upstream 404. The report includes actual JSON responses. This is a time-stamped observation, not a guarantee that a third-party site will remain unchanged.

The deterministic suite includes simulated 429/5xx, network timeouts, robots denial and renewal, malformed HTML, hostile source links, unexpected redirects, bad encoding, response-size limits, cache eviction, concurrent requests, cancelled retries and total-request cancellation. These failure cases are simulated locally, not induced on the public website.

One upstream deprecation warning is emitted by the pinned Starlette TestClient when using HTTPX. Tests pass with this combination; the warning is not suppressed. Runtime HTTP calls use HTTPX directly. Dependency upgrades should be tested rather than applied blindly.

**Not executed:** Docker image build/run, remote GitHub Actions, Windows execution, production load testing, Agent Studio integration or paid services. Windows commands are supplied as standard virtual-environment instructions; only Linux execution was recorded. No model-quality or business-impact metric is claimed.

To reproduce, install `requirements-dev.txt`, run `python -m pytest -q`, then run `python scripts/demo.py --mode fixture` and, with internet access, `python scripts/demo.py --mode live`. Each script exits nonzero on failure.
