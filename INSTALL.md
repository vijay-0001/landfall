# Install and run Landfall

Landfall has two websites that run side by side: **Landfall** (the console where the seller works, and the duties API) and **Kiln & Co.** (a make-believe merchant shop, used to show a real checkout). This page gets both running on your machine, then walks the demo. For what Landfall is and why, see the [README](README.md).

## What you need

| | |
|---|---|
| **Docker** (with Compose v2) | runs everything in Option A, and the database in Option B |
| **Python 3.11+** and **Node 24** | Option B (local development) and running the tests |
| **An Anthropic API key** | the AI that recommends customs codes (Claude Haiku). The first start records the demo shop's recommendations, about a cent per product |
| **A PayPal sandbox app** | a client id and secret from <https://developer.paypal.com> (Apps & Credentials, Sandbox). Used by the Kiln shop |
| **A PayPal sandbox buyer account** | to approve the test payment in PayPal's popup. Sandbox only: no real money moves |

None of these is in the repository. Keys live only in a local `.env` file, which git ignores.

## 1. Get the code and create your `.env`

```bash
git clone <this repository> landfall && cd landfall
cp .env.example .env
```

Open `.env` and set at least these (the file's comments say what each is):

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your key |
| `POSTGRES_PASSWORD` | any password (Option A) |
| `LANDFALL_SIGNING_KEY` | a random secret that signs quotes: `python -c "import secrets;print(secrets.token_hex(32))"` |
| `LANDFALL_KILN_API_KEY` | the demo shop's key: `python -c "import secrets;print('lf_test_'+secrets.token_hex(24))"` |
| `KILN_PAYPAL_CLIENT_ID`, `KILN_PAYPAL_CLIENT_SECRET` | your PayPal sandbox app |
| `KILN_ADMIN_PASSWORD` | 10+ characters; turns on Kiln's staff login and back office (user name `owner`) |
| `LANDFALL_ALLOW_SIGNUP` | `1` to let you open merchant accounts locally. **Closed by default**, keep it closed on any public server |

## 2. Option A: everything in containers (simplest)

```bash
docker compose -f infra/docker-compose.yml --env-file .env --profile standalone up -d --build
```

This builds and starts the console (web), the API, the nightly worker, the share-image renderer, PostgreSQL, Kiln, and a Caddy proxy on port 80. The first start takes a few minutes.

For local use add these to `.env` first:

```
PUBLIC_URL=http://localhost
SITE_ADDRESS=:80
KILN_ADDRESS=kiln.localhost
KILN_PUBLIC_URL=http://kiln.localhost
```

Then open:

- **Landfall console:** <http://localhost>
- **Kiln & Co. shop:** <http://kiln.localhost> (browsers send `*.localhost` to your own machine; if yours does not, add `127.0.0.1 kiln.localhost` to your hosts file)
- **Health check:** <http://localhost/api/health> should answer `{"status":"ok"}`

Stop it with `docker compose -f infra/docker-compose.yml --env-file .env --profile standalone down`.

## 3. Option B: local development

Runs the four apps directly, with only PostgreSQL in a container. Use this to change code.

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt        # Windows: .venv/Scripts/python
docker run -d --name landfall-pg -e POSTGRES_PASSWORD=landfall -p 55432:5432 postgres:16
docker exec landfall-pg psql -U postgres -c "CREATE DATABASE landfall_demo"
(cd apps/renderer && npm ci) && (cd apps/web && npm ci)
```

**Windows (Git Bash):** one script starts everything and rebuilds the console:

```bash
LANDFALL_WALK_URL="postgresql+pg8000://postgres:landfall@localhost:55432/landfall_demo" bash scripts/restart_local.sh
```

**Linux or macOS:** start the four processes yourself, each in its own terminal, from the repository root (load `.env` first, for example `set -a; . ./.env; set +a`):

```bash
# 1. API (creates its tables and the demo seed on first start)
LANDFALL_ALLOW_SIGNUP=1 LANDFALL_ALLOW_PRIVATE_FEEDS=1 LANDFALL_UK_ONDEMAND=off RENDERER_URL=http://127.0.0.1:3300 \
LANDFALL_DATABASE_URL=postgresql+pg8000://postgres:landfall@localhost:55432/landfall_demo \
.venv/bin/python -m uvicorn landfall_api.main:app --port 8000

# 2. Share-image renderer
(cd apps/renderer && PORT=3300 WEB_URL=http://127.0.0.1:3000 node server.mjs)

# 3. Kiln & Co. (the mock merchant)
(cd apps/kiln && PORT=3400 LANDFALL_API_URL=http://127.0.0.1:8000 LANDFALL_PUBLIC_API_URL=http://127.0.0.1:8000 \
 LANDFALL_CONSOLE_URL=http://127.0.0.1:3000 KILN_PUBLIC_URL=http://127.0.0.1:3400 \
 KILN_ADMIN_USER=owner KILN_ADMIN_PASSWORD="$KILN_ADMIN_PASSWORD" node server.mjs)

# 4. The Landfall console
(cd apps/web && API_PROXY_TARGET=http://127.0.0.1:8000 API_INTERNAL_URL=http://127.0.0.1:8000 npm run build \
 && API_INTERNAL_URL=http://127.0.0.1:8000 npx next start -p 3000 -H 127.0.0.1)
```

Open the console at <http://127.0.0.1:3000>, Kiln at <http://127.0.0.1:3400>, and check <http://127.0.0.1:8000/api/health>.

**Keep the rates fresh.** Duty rates come from official sources and are refreshed by a nightly worker (the container in Option A does this). In Option B run it once: `.venv/bin/python -m landfall_worker.main`. If rates have not been refreshed for 7 days, Landfall pauses "duties included" rather than guess.

## 4. Try it (about five minutes)

1. Open **Kiln** and click the mug. The price is in the buyer's currency and no import duty is included yet.
2. Open the **Landfall console**, choose **Connect your store**, open an account, paste Kiln's feed address (`<Kiln address>/products.json`) and press **Import products**, then **Get recommendations for all**.
3. In **Products**, open the mug, answer its one question, and **Accept**. The AI recommends; you decide.
4. On Landfall's **API keys** page, copy the secret key. In Kiln, **Staff login** (user `owner`), **Shop admin**, **Landfall connection**: paste it and press **Check and save**.
5. Back in Kiln, the mug now says **Duties included**. Add it to the cart and check out. You should see duty **$7.60** and a total of **$59.60** (item $38 + shipping $14 + duty).
6. Press the PayPal button, log in as your **sandbox buyer** in PayPal's popup, and approve. Kiln's server checks the order against Landfall's signed quote, then captures. The receipt shows the duty.

## 5. Run the tests

```bash
.venv/bin/python -m pytest -q                      # Python: engine, register, classifier, API (recorded fixtures only, no live internet)
(cd apps/kiln && node --test)                      # the mock merchant, against a fake Landfall and a fake PayPal
(cd apps/web && npm run typecheck && npm run lint && npm test)
scripts/ci licences                                # fails on GPL, AGPL, SSPL, BSL or commercial-only dependencies
```

The end-to-end browser tests (`cd apps/web && npx playwright test`) start the whole stack themselves and need a clean database.

## Putting it on a public server

Set `LANDFALL_DEMO_READONLY=1` in the server's `.env`. Without it, anyone who can reach the console can change the sample shop, ask the assistant and run the AI (which spends your Anthropic tokens), and can approve rule proposals that change the rate register. With it, a visitor without an API key can still read every recommendation and price, but those calls answer "read-only". Keep merchant sign-up closed (leave `LANDFALL_ALLOW_SIGNUP` unset), and set a monthly spend limit on your Anthropic account as a second safety net.

## Troubleshooting

- **The console says no store is connected.** That is the first-run state: open an account under *Connect your store*.
- **Kiln shows no prices, or "Landfall could not be reached".** Kiln needs Landfall running and its key connected (step 4 above, or `LANDFALL_KILN_API_KEY` in `.env`).
- **"Duties included" is missing on a product.** The seller has not accepted it yet, or the rates have not been refreshed for 7 days (run the worker).
- **No PayPal button.** Check `/api/config` on Kiln and that `KILN_PAYPAL_CLIENT_ID` is set, and that the browser can reach PayPal.
- **Port already in use.** Stop whatever uses 80, 3000, 3300, 3400, 8000 or 55432, or change the ports.

Deploying behind an existing reverse proxy on a server: [`infra/vps-deploy.md`](infra/vps-deploy.md).
