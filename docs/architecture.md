# Landfall: solution architecture

One VPS, Docker Compose, six containers, four images built in CI. This is the text version of the diagram in the HLD (https://claude.ai/artifact/DReaMKj5Ti6o4y9nGob7KD).

```mermaid
flowchart TB
  subgraph users[Browsers]
    S[Seller]; B[Buyer]; V[Public visitor]; O[Ops reviewer]
  end
  users -->|HTTPS| caddy
  subgraph vps[One VPS, Docker Compose]
    caddy[caddy: reverse proxy, automatic HTTPS]
    web[web: Next.js, React, TypeScript, TanStack Table, Recharts]
    api[api: FastAPI, Pydantic, SQLAlchemy: recommender, duty engine, checkout, rules]
    worker[worker: Python, APScheduler, httpx, lxml: nightly sync, rule drafts]
    renderer[renderer: Playwright, headless Chromium: share PNGs]
    db[(db: PostgreSQL: the rate register)]
    caddy -->|/| web
    caddy -->|/api| api
    web --> api
    api -->|image request| renderer
    api --> db
    worker --> db
  end
  api --> PayPal[PayPal Orders v2, sandbox: duty sent as tax]
  api --> Claude[Claude API: Haiku only]
  api --> Easyship[Easyship: duty quote, UK to US DDP shipment; Shippo is backup, US origin only]
  worker --> Claude
  worker --> Sources[USITC HTS, Federal Register, UK Trade Tariff, EU TEDB and TARIC]
```

## Rules the architecture depends on

- Checkout never calls the model. It reads accepted classifications and the rate register only.
- Every price is a register read at a stated date. Orders lock the register version they used.
- Only `caddy` publishes ports (80, 443). Everything else is on a private Docker network.
- Secrets live in a protected `.env` on the server, never in images or git.
- The database is on a named volume; a nightly `pg_dump` is copied off the VPS.
- CI builds four images (web, api, worker, renderer); the VPS pulls them and runs `docker compose up -d`.
- VPS size: 4 GB RAM or more (Chromium in the renderer needs about 1 GB).
- Licences: permissive only. CI fails the build on copyleft or source-available licences.
