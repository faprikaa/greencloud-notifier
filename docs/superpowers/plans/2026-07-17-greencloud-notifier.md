# GreenCloud Notifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Monitor four approved GreenCloud VPS products and send Telegram notifications on EVERY positively available check from Docker.

**Architecture:** A sequential Python polling loop fetches product pages, conservatively classifies stock, and delivers Telegram notifications every time availability is confirmed. No deduplication or persistent state is needed. Network failures remain unknown and never imply stock availability.

**User revision — execution precedence:** The user explicitly requests repeated notifications. Task 4's persistence/transition design below is superseded in its entirety: replace it with tests proving that two consecutive available checks send two messages, available→unknown sends only one, and failed delivery retries only after a fresh available check. Implement a simple available-only delivery gate, not `state.py`. In Tasks 5–6 omit state loading, state volumes, state-writability tests, and duplicate-suppression claims. Document intentional repeated messages instead. Keep timeouts, backoff, and Telegram rate-limit handling. No state-file configuration is needed.

**Tech Stack:** Python 3.12, requests, beautifulsoup4, unittest, Docker Compose.

---

## Context and file boundaries

Approved design: `docs/superpowers/specs/2026-07-17-greencloud-notifier-design.md`.
The directory is not a Git repository. Do not assume commits or worktree isolation are available; do not initialize Git merely to satisfy a workflow.

Files to create:
- `notifier/__init__.py`: package marker.
- `notifier/config.py`: fixed product list and validated environment configuration.
- `notifier/stock.py`: HTTP fetching and pure HTML classification.
- `notifier/state.py`: validated persistent state and atomic writes.
- `notifier/telegram.py`: Telegram API delivery with sanitized errors.
- `notifier/__main__.py`: orchestration, retry pacing, signals, and logs.
- `tests/test_config.py`, `tests/test_stock.py`, `tests/test_state.py`, `tests/test_telegram.py`, `tests/test_monitor.py`: offline unit and integration coverage.
- `tests/fixtures/sold_out.html`: minimal sanitized real sold-out markup.
- `tests/fixtures/configure.html`: explicitly synthetic positive fixture until live available markup can be inspected.
- `requirements.txt`, `Dockerfile`, `compose.yaml`, `.env.example`, `.gitignore`, `.dockerignore`, `README.md`.

## Task 1: Establish stock evidence before implementation

- [ ] Fetch each approved URL using bounded GET requests with English language selected. Inspect redirects, final URL, and the order area. Never submit an order form or purchase request.
- [ ] Record only sanitized relevant HTML in fixtures, excluding cookies, session IDs, and hidden security tokens.
- [ ] Use this observed sold-out marker (already found on `budgetkvmsgdc1-3`):

```html
<div id="order-standard_cart">
  <div class="alert alert-danger error-heading">Out of Stock</div>
  <p>We are currently out of stock on this item so orders for it have been suspended until more stock is available.</p>
</div>
```

- [ ] Inspect category/product markup for product identity and real configuration form evidence. If no available product can be observed safely, label the positive fixture synthetic and explicitly document that live positive detection remains unverified. A cart navigation link or language menu link is not availability evidence.
- [ ] Define the pure classifier interface as `classify(html: str, slug: str) -> str`, returning exactly `available`, `unavailable`, or `unknown`. Require expected product identity inside the order content, a product-specific configuration form, and an enabled continuation control for availability. Reject challenges, ambiguous pages, and contradictory evidence as unknown.

## Task 2: Configuration and classifier, test-first

- [ ] Create configuration tests covering all four fixed slugs, the default interval of 60 seconds, blank token/chat ID, and invalid/nonfinite/too-small intervals. Accept numeric interval values of at least 30 seconds. Permit negative Telegram group chat IDs.
- [ ] Write classifier tests before implementation, including this behavioral matrix:

```python
cases = [
    ("sold_out.html", "unavailable"),
    ("configure.html", "available"),
]
for fixture, expected in cases:
    with self.subTest(fixture=fixture):
        html = (FIXTURES / fixture).read_text()
        self.assertEqual(classify(html, "budgetkvmsgdc1-3"), expected)
self.assertEqual(classify("<html>Just a moment...</html>", "budgetkvmsgdc1-3"), "unknown")
self.assertEqual(classify("<a href='/billing/cart.php?a=view'>Cart</a>", "budgetkvmsgdc1-3"), "unknown")
```

- [ ] Add tests for wrong product identity, disabled continuation, navigation-only identity, missing form, conflicting markers, and HTML with sold-out words only in a script. Classify visible order content, not arbitrary script text.
- [ ] Run `rtk python3 -m unittest discover -s tests -v`; confirm missing implementation causes failure.
- [ ] Implement `config.py` with immutable product URLs and startup validation. Implement `stock.py` with the exact verified DOM evidence from Task 1, using BeautifulSoup, not a page-wide substring for positive detection.
- [ ] Pin tested requests and beautifulsoup4 versions in `requirements.txt`, install them in a local virtual environment, and rerun tests using that environment's Python until green.

## Task 3: Fetching and safe Telegram delivery

- [ ] Write mocked HTTP tests before implementation: timeout, connection failure, 403, 429, 500, non-HTML product content, foreign or unexpected redirects, Telegram HTTP 200 with `ok=false`, success, and malformed Telegram JSON.
- [ ] Use `fetch_stock(session, product) -> str` and `send_message(session, token, chat_id, text) -> bool` as boundaries. Assert that error paths do not print the token or requests exception URLs.
- [ ] Run `rtk .venv/bin/python -m unittest discover -s tests -v` and confirm new tests fail.
- [ ] Implement fetches with connect/read timeouts of 5/20 seconds, English language selection, a descriptive user agent, and a maximum response size of 2 MiB. Validate final host and product routing before classification; foreign/unrecognized redirects return unknown. Do not retry in a tight per-request loop.
- [ ] Implement Telegram POST `sendMessage` using plain text (no parse mode), `chat_id`, `text`, and disabled link previews. Require HTTP success and JSON `ok` exactly true. Bound response processing and catch network/JSON failures; return false and log only safe status/error categories.
- [ ] For rate-limited/transient failures, defer retries to the polling scheduler. Honor a valid Retry-After longer than the configured interval, with a conservative upper bound of one hour. Keep non-network classifier and state code independent of requests exceptions.
- [ ] Rerun tests; verify requests are mocked and no real messages are sent.

## Task 4: Durable transition state and delivery retries

- [ ] Write state tests using temporary directories: missing file, valid reload, invalid JSON, unknown version, invalid field types, atomic replacement, and preservation of the old file when writing fails.
- [ ] Persist schema version 1 with each known slug mapped to `confirmed` (`available`, `unavailable`, or null) and `notified` (boolean). Validate invariants: `notified=true` is only valid with confirmed available. Reject corrupt state with an actionable startup error.
- [ ] Write orchestration tests for the following transitions before implementation:

```text
initial -> available: deliver once; persist notified only on success
available/notified -> available: no delivery
available/notified -> unknown -> available: no delivery
available/notified -> unavailable -> available: deliver again
initial -> available/delivery failed -> available: retry delivery
available/delivery failed -> unavailable: clear pending availability
restart with available/notified -> available: no delivery
```

- [ ] Run tests and confirm new cases fail.
- [ ] Implement atomic persistence using a temporary file in the same directory, flush/fsync, then `os.replace`. Save confirmed transitions before network delivery, and successful delivery afterward. Failed persistence is fatal rather than silently continuing with unsaved notification history.
- [ ] Keep `observe(product, status, state, notify)` as an injected, offline-testable orchestration boundary. Unknown observations must not change confirmed stock state. Retry failed delivery only on a fresh available observation, not on stale availability during unknown checks.
- [ ] Rerun all tests. Document the unavoidable duplicate window between successful Telegram delivery and the subsequent state write; do not claim exactly-once delivery.

## Task 5: Runtime loop, Docker, and documentation

- [ ] Write monitor tests with fake sessions and injected stop/wait behavior: four sequential checks, startup config failure, SIGTERM-like stop, error backoff, and no credentials in captured logs.
- [ ] Run tests to establish failure before implementing the runtime loop.
- [ ] Implement `python -m notifier`: validate configuration, load `/data/state.json` (overridable by `STATE_FILE`), initialize sessions, check products sequentially, and wait after each complete sweep. Use `threading.Event.wait` for interruptible sleeps and handlers for SIGINT/SIGTERM. Back off consecutive network failures to 2, 4, 8, then at most 15 minutes, never shorter than the configured interval or valid server retry delay. Reset transient backoff after successful requests.
- [ ] Log startup, product status changes, unknown reasons, delivery results, and shutdown. Never log environment contents, tokens, or token-bearing Telegram request URLs.
- [ ] Add this environment template:

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
CHECK_INTERVAL_SECONDS=60
```

- [ ] Build a Python 3.12 slim Docker image, install pinned requirements without cache, copy only runtime files, run as a non-root user, and create a writable `/data` directory owned by that user. Use exec-form `CMD ["python", "-m", "notifier"]`.
- [ ] Add Compose service `notifier` with `build: .`, `env_file: .env`, `restart: unless-stopped`, a named volume at `/data`, and bounded Docker log rotation. Exclude `.env`, `.venv`, `.git`, state files, caches, and local docs/tests from the image context unless explicitly needed by the build.
- [ ] Write Indonesian README instructions for BotFather, starting a private bot chat, obtaining `chat.id` via getUpdates locally without sharing the token, copying `.env.example`, and filling credentials. Include these commands:

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f --tail=100
docker compose down
```

- [ ] Explain that `docker compose down` preserves state but `down -v` deletes it, duplicate delivery is possible after a crash, polling is not reservation/purchase, markup changes can yield unknown, and browser automation/protection bypass is not included. Include offline test commands and required live-positive verification caveats.

## Task 6: Verification and handoff

- [ ] Run `rtk .venv/bin/python -m unittest discover -s tests -v` and `rtk .venv/bin/python -m compileall -q notifier tests`; preserve exact outcomes.
- [ ] Validate Compose with dummy credentials in a temporary env file, without printing a real token. Run `rtk docker compose --env-file /tmp/greencloud-test.env config --quiet` only after arranging the service env_file to use a safe test file or temporary `.env`; do not overwrite an existing user `.env`.
- [ ] Run `rtk docker build -t greencloud-notifier:test .` if Docker is available. Smoke-test container configuration failure without secrets, and state directory writability under the image's non-root user.
- [ ] Run a bounded live read-only check of the four products only. Report observations as snapshots, not claims of future stock or guaranteed positive detection.
- [ ] Review implementation against the approved spec: exact four products, safe positive evidence, persistent state, failed delivery retries, rate limits, credential hygiene, graceful shutdown, and Indonesian setup documentation.
- [ ] Report files created, exact checks passed, checks blocked by environment, and credential-dependent Telegram delivery not yet verified. Do not claim a real Telegram message was delivered without credentials and observed API success.
