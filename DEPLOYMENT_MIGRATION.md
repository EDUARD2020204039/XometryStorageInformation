# Deployment migration

This sequence keeps the current public hostname working while the canonical XSI endpoint is introduced.

## 1. Deploy compatible services

1. Back up the production database and the bot state directory.
2. Deploy `xometry-app`, `xometryanaliza`, and `xometry-bot` on the same Docker network.
3. Keep `XSI_API_AUTH_REQUIRED=false` during this compatibility stage.
4. Configure the internal URLs with Docker service names; do not use LAN or public IP addresses between containers.
5. Verify `/api/health`, `/api/ready`, the offers page, the orders page, and one non-destructive history lookup.

## 2. Publish the canonical hostname

1. Add `xsi.habaresearch.eu` as a Cloudflare Tunnel public hostname pointing to `http://xometry-app:10000`.
2. Keep `xometrystorageinformation.habaresearch.eu` routed to the same service during migration.
3. Do not implement `xsi` as an HTTP redirect: extension POST and WebSocket traffic must reach the service directly.
4. Restrict the Unraid port so it is reachable through the tunnel and Docker network, not exposed directly to the internet.

## 3. Roll out extension settings

1. Load the extension build and confirm it is active by default.
2. Verify that disabling it from the options page prevents UI injection after a Xometry page reload.
3. Verify scrape, history lookup, and analysis against the long compatibility hostname.
4. After `xsi` is healthy, change `backendBaseUrl` in `XometryExtension/config.js` to the canonical hostname and publish a new extension version.

## 4. Enable API authentication

1. Generate a dedicated random `XSI_API_TOKEN`; do not reuse a user password or Cloudflare credential.
2. Configure the same token in the bot and in the extension options.
3. Set `XSI_API_AUTH_REQUIRED=true` and redeploy `xometry-app`.
4. Confirm unauthenticated ingestion returns `401` and authenticated ingestion succeeds.
5. Rotate the token if it was ever copied into logs or chat.

## 5. Validate order semantics

The database intentionally stores one row per PO part. Compare Xometry's profile count with `total_orders` (distinct PO IDs), not `total_rows`. Reprocess recent order pages after deployment so changed PO status and amounts are updated.

## Rollback

Restore the previous container image and keep both public hostnames routed to it. Database changes in this phase are additive; the new API routes and response fields do not remove the legacy contracts.
