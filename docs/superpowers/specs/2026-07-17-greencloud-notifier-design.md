# GreenCloud stock notifier

## Approved scope
A lightweight Python service running with Docker Compose monitors exactly these four product URLs:

- https://greencloudvps.com/billing/store/budget-kvm-sale/budgetkvmsgdc1-2
- https://greencloudvps.com/billing/store/budget-kvm-sale/budgetkvmsgdc1-3
- https://greencloudvps.com/billing/store/budget-kvm-sale/budgetkvmsg-3
- https://greencloudvps.com/billing/store/budget-kvm-sale/budgetkvmsg-2

The category page is not a subscription to additional products. The service only monitors stock; it never orders or purchases a VPS.

## Architecture
Use Python HTTP requests and HTML parsing, not a browser by default. Inspect actual product responses before implementing detection. Separate fetching, stock classification, persistent notification state, and Telegram delivery so each can be tested independently. Browser automation is outside this initial scope; if ordinary HTTP cannot expose reliable stock evidence, report that limitation rather than guessing availability.

## Stock classification
Each check returns available, unavailable, or unknown. Available requires positive evidence of an actionable order/configuration flow associated with the intended product. Explicit sold-out evidence means unavailable. HTTP failures, rate limits, protection pages, unexpected redirects, ambiguous content, and unrecognized markup mean unknown. A generic successful HTTP response or absence of sold-out text is not proof of availability.

## Notifications
User revision: send a Telegram message containing the product name and canonical order URL on EVERY check that positively confirms availability, including the first check and consecutive available checks. Repeated notifications are intentional; there is no deduplication, cooldown, or persistent notification history. Unavailable or unknown observations do not send stock notifications. Failed delivery can be tried again on the next positively available check, never from stale evidence. Respect Telegram rate limits and network backoff despite the user's acceptance of repeated notifications.

## Configuration and operations
Read TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, and CHECK_INTERVAL_SECONDS from environment variables; default interval is 60 seconds. Provide .env.example with placeholders and exclude real .env files from version control and Docker build context. Do not log tokens or token-bearing Telegram URLs. Run with docker compose up -d and a restart policy; a persistent state volume is not needed. Use bounded request timeouts, sequential product checks, a bounded retry/backoff policy for transient failures, and graceful shutdown. Rate limiting must not cause a tight retry loop. Log product status changes and actionable errors without exposing credentials.

## Verification and deliverables
Deliver application code, pinned dependencies, Dockerfile, compose.yaml, .env.example, automated tests, and an Indonesian README covering bot setup, chat ID discovery, configuration, startup, logs, and limitations. Test representative available/unavailable HTML, challenge pages, ambiguous pages, request failures, notifications on consecutive available checks, unknown-state behavior, and failed delivery retries on fresh available observations with offline fixtures and mocked network calls. Validate Docker configuration and build where Docker is available. Live stock observations are snapshots, not a guarantee of future detector compatibility. Actual Telegram delivery requires user-supplied credentials and is not claimed verified without them.
