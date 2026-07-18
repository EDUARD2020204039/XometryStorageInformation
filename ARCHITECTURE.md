# Xometry system architecture

## Purpose

This repository is the system of record and automation layer around the Xometry Partner Portal. It must work both inside and outside the company network without exposing Unraid or workstation ports directly.

## Canonical topology

```text
Xometry Partner Portal
        |
        +-- Chrome extension -- HTTPS/WSS --> xsi.habaresearch.eu
        |                                      |
        |                               Cloudflare Access/WAF
        |                                      |
        |                               Cloudflare Tunnel
        |                                      |
        |                               xometry-app:10000
        |
        +-- xometrybot-scraper --------------------+
                    |                              |
                    +--> xometry-app:10000         |
                    +--> xometryanaliza:4468 <-----+
                    +--> Telegram

xometryanaliza:4468 --> Ofertare Automata / SFTP / local dosar storage
```

Only Cloudflare is public. Docker services communicate by service name on the private Docker network. Unraid ports are not application API addresses and must never be compiled into the extension.

## Service ownership

### `xometry-app`

Owns durable business data and the operator UI:

- offers and their parts;
- purchase orders and their parts;
- part occurrence/history queries;
- dossier metadata and exports;
- public API contracts used by the extension;
- ingestion contracts used by the scraper.

It must not scrape Xometry or run geometry agents.

### `xometry_bot`

Owns Xometry acquisition and notifications:

- authenticated browser/GraphQL access;
- offer discovery and extraction;
- order synchronization;
- Telegram notifications;
- delivery of normalized payloads to `xometry-app`;
- submission of analysis jobs to `xometryanaliza`.

It must not become a second database.

### `XometryAnaliza`

Owns long-running and machine-local processing:

- persistent analysis queue;
- GEO/STEP/bend processing;
- Ofertare Automata coordination;
- watchdogs, diagnostics and artifacts;
- local dossier/workspace integration.

It stores operational state, not the canonical offer/order history.

### `XometryExtension`

Owns browser-side extraction and operator controls. It is a client, not a trusted secret store.

- one canonical extension source must live in this repository;
- its backend URL comes from one configuration module;
- the default public API is `https://xsi.habaresearch.eu`;
- old public/LAN IP fallbacks are forbidden;
- API errors must be explicit and time-bounded;
- credentials must be per-install and revocable, never committed.

## Network names

| Use | Canonical address |
| --- | --- |
| Public UI/API | `https://xsi.habaresearch.eu` |
| Public analysis UI (operator only) | `https://qa.habaresearch.eu` |
| Bot to app | `http://xometry-app:10000` |
| Bot/app to analysis | `http://xometryanaliza:4468` |

The legacy hostname `xometrystorageinformation.habaresearch.eu` remains available during migration. API clients call the canonical hostname directly; they do not rely on 301/302 redirects for POST requests.

## Data contracts

An Xometry PO is not a row in the `orders` table. A PO contains one or more parts. Until the database migration separates `purchase_orders` and `purchase_order_parts`, APIs must expose both concepts explicitly:

- `total_orders`: count of distinct `order_id` values;
- `total_rows`: count of stored part rows;
- `orders`: part-level records for backward compatibility.

Part history combines:

- exact Part ID;
- normalized full filename/drawing code;
- material compatibility;
- dimension compatibility;
- source (`offer` or `purchase_order`);
- a score and human-readable reasons.

Low-confidence candidates are never labelled as the same part.

## API lifecycle

- Existing `/api/*` routes remain compatible during the first refactor.
- New contracts use `/api/v1/*`.
- Write endpoints require a bearer/API token when `XSI_API_AUTH_REQUIRED=true`.
- Cloudflare Access protects human-facing UI routes.
- `/api/health` is shallow; `/api/ready` verifies the database and dependencies.
- Every response includes `X-Request-ID`.

## Order synchronization rules

1. Initial backfill walks all order pages once.
2. Incremental runs always refresh the first configurable number of recent pages so status changes are captured.
3. Seen-order state is persisted only after the backend accepts the batch.
4. A database uniqueness constraint protects `(order_id, part_id)`.
5. UI counts distinguish PO count from part-row count.

## Migration sequence

1. Add configuration, authentication hooks, readiness and versioned contracts without breaking legacy clients.
2. Publish `xsi.habaresearch.eu` to the existing Cloudflare Tunnel.
3. Update the canonical extension and scraper to the new contracts.
4. Backfill/reconcile order data and deploy part history.
5. Enable required API authentication.
6. Split the monolithic FastAPI files into routers/services.
7. Remove legacy IPs, duplicate routes and compatibility paths after an observed deprecation window.

