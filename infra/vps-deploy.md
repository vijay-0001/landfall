# Deploying Landfall behind an existing reverse proxy

Landfall runs as its own compose project, publishes no port, and is reached through a reverse proxy that already owns ports 80 and 443.

1. Copy the repository (no `.env`, no `node_modules`) and a server `.env` (mode 600) to the server. Set a fresh `POSTGRES_PASSWORD`, `LANDFALL_SIGNING_KEY`, `PUBLIC_URL`, and `SHARED_PROXY_NETWORK` (the docker network the proxy is on).
2. `docker compose -f infra/docker-compose.yml -f infra/docker-compose.vps.yml --env-file .env up -d --build`. Check that no new port is published.
3. DNS: an A record for the site name (and one for the Kiln demo shop) pointing at the server, before the HTTPS block is added.
4. Back up the proxy's config, add a block that proxies the site name to the `landfall-web` alias (and the Kiln name to `landfall-kiln`), validate, and reload gracefully.
5. Check `GET /api/health`, then a quote for the demo mug (total 59.60, tax 7.60).

Rollback: restore the proxy config, reload, and `docker compose down` in the Landfall folder. Nightly backup: `infra/backup.sh`.
