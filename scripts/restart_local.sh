#!/usr/bin/env bash
# Restart the local UI stack on ports 8000 (API), 3300 (renderer), 3000 (web), 3400 (Kiln & Co., the mock merchant) against the walkthrough database. Logs go to $TEMP.
# The mock merchant's API key is read from .env (LANDFALL_KILN_API_KEY) and never printed. Private feed addresses are allowed here only so Landfall can read Kiln's feed on localhost.
cd "$(dirname "$0")/.."
for port in 3000 3300 3400 8000; do
  for pid in $(netstat -ano | grep -E "[:.]$port .*LISTENING" | awk '{print $5}' | sort -u); do taskkill //PID "$pid" //F //T >/dev/null 2>&1; done
done
sleep 2
envget() { grep -m1 "^$1=" .env | cut -d= -f2- | tr -d '\r'; }
KILN_KEY=$(envget LANDFALL_KILN_API_KEY)
# Landfall's quote-signing key: generated into .env once, never printed.
if [ -z "$(envget LANDFALL_SIGNING_KEY)" ]; then printf '\nLANDFALL_SIGNING_KEY=%s\n' "$(.venv/Scripts/python -c 'import secrets;print(secrets.token_hex(32))' | tr -d '\r')" >> .env; fi
SIGNING_KEY=$(envget LANDFALL_SIGNING_KEY)
# Kiln's staff login for its back office (user "owner"): generated into .env once, never printed. Read it from .env (KILN_ADMIN_PASSWORD).
if [ -z "$(envget KILN_ADMIN_PASSWORD)" ]; then printf '
KILN_ADMIN_USER=owner
KILN_ADMIN_PASSWORD=%s
' "$(.venv/Scripts/python -c 'import secrets;print(secrets.token_urlsafe(12))' | tr -d '')" >> .env; fi
KILN_ADMIN_PW=$(envget KILN_ADMIN_PASSWORD)
# Kiln is a merchant with its own PayPal credentials (here the same sandbox app, copied from the PAYPAL_ lines; never printed).
KILN_PP_ID=$(envget PAYPAL_CLIENT_ID); KILN_PP_SECRET=$(envget PAYPAL_CLIENT_SECRET)
(LANDFALL_ALLOW_SIGNUP=1 LANDFALL_SIGNING_KEY="$SIGNING_KEY" LANDFALL_ALLOW_PRIVATE_FEEDS=1 LANDFALL_DATABASE_URL=${LANDFALL_WALK_URL:-postgresql+pg8000://postgres:landfall@localhost:55432/landfall_walk} LANDFALL_UK_ONDEMAND=off RENDERER_URL=http://127.0.0.1:3300 .venv/Scripts/python -m uvicorn landfall_api.main:app --port 8000 > "$TEMP/api.log" 2>&1 &)
(cd apps/renderer && PORT=3300 WEB_URL=http://127.0.0.1:3000 node server.mjs > "$TEMP/renderer.log" 2>&1 &)
(cd apps/kiln && PORT=3400 LANDFALL_API_URL=http://127.0.0.1:8000 KILN_ADMIN_USER=owner KILN_ADMIN_PASSWORD="$KILN_ADMIN_PW" LANDFALL_PUBLIC_API_URL=http://127.0.0.1:8000 LANDFALL_CONSOLE_URL=http://127.0.0.1:3000 LANDFALL_KILN_API_KEY="$KILN_KEY" KILN_PAYPAL_CLIENT_ID="$KILN_PP_ID" KILN_PAYPAL_CLIENT_SECRET="$KILN_PP_SECRET" KILN_PUBLIC_URL=http://127.0.0.1:3400 node server.mjs > "$TEMP/kiln.log" 2>&1 &)
if [ "$1" != "--no-build" ]; then (cd apps/web && API_PROXY_TARGET=http://127.0.0.1:8000 API_INTERNAL_URL=http://127.0.0.1:8000 npm run build > "$TEMP/webbuild.log" 2>&1) || { tail -20 "$TEMP/webbuild.log"; exit 1; }; fi
# Password gate: SITE_PASSWORD in .env turns it on. Open the console at http://localhost:3000 (the gate guards that address; the renderer
# uses 127.0.0.1 and so is not gated). No SITE_PASSWORD in .env means no gate.
SITE_PW=$(envget SITE_PASSWORD); GATE_URL=""; [ -n "$SITE_PW" ] && GATE_URL=http://localhost:3000
(cd apps/web && SITE_PASSWORD="$SITE_PW" PUBLIC_URL="$GATE_URL" API_INTERNAL_URL=http://127.0.0.1:8000 npx next start -p 3000 -H 127.0.0.1 > "$TEMP/web.log" 2>&1 &)
until curl -s -m 3 http://127.0.0.1:8000/api/health | grep -q ok; do sleep 3; done
echo up
