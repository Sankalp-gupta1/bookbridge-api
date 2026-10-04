# AI assistance and review

This submission was developed with substantial assistance from ChatGPT/Codex for implementation, test design, documentation and debugging. It should not be represented as unaided work.

Checks used to validate generated output:

- Compared parsing with original public HTML, including full-title attributes, GBP encoding, the UPC table, pagination and relative links.
- Ran deterministic regression and simulated-failure tests rather than relying only on successful requests.
- Ran an actual local HTTP demonstration against captured fixtures and separately against the live site.
- Kept machine-readable test results and capture checksums for reviewer inspection.

A concrete correction: the original timeout wrapped HTTP middleware. A regression test showed that the API could return a timeout while the upstream task kept running. The deadline was moved into the actual route handler so cancellation reaches the HTTP fetch and releases the source lock. A second regression test verifies that cancelling a short `Retry-After` sleep does not let the next caller bypass the source cooldown.

The code is a prototype with documented limitations. No production merchant deployment, business impact, model accuracy score, remote CI pass or Docker execution is claimed. The candidate should review the implementation and be prepared to explain the data flow, failure behaviour and design trade-offs before submitting or discussing it.
