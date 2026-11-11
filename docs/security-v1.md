# Security items for v1

What is in place today is enough for a hackathon demo on sandboxes. These items are **not built** and should be done before Landfall is released as v1 or runs for merchants other than the demo merchant. Each says what exists now and what is missing.

| # | Item | Today | Before v1 |
|---|---|---|---|
| 1 | **CORS origin allowlist and publishable-key scoping** | The API answers `Access-Control-Allow-Origin: *` (no credentials). The publishable key is accepted only on `POST /api/quote` and can only ask for a quote. | Each merchant lists the origins of its checkout; the API answers only those. Scope the publishable key to its origins, rate-limit it per key and per IP, and let a merchant rotate it. |
| 2 | **Sign-up rate limiting and abuse controls** | Sign-up is closed by default (`LANDFALL_ALLOW_SIGNUP=1` opens it, local runs only). No rate limit once open. | Rate limit by IP and by feed host; bot protection; email verification; a per-merchant cap on products and on model calls (each new product can cost a Haiku call). |
| 3 | **Key rotation and revocation** | A key is shown once and only its hash is stored. There is no way to replace or revoke it. | Rotate and revoke from the console, with an overlap period; audit every key use; alert on keys used from new places. |
| 4 | **A real console login and teams** | The console is signed in by pasting the API key into the browser. | Proper accounts (passwordless or SSO), roles (owner, reviewer), and a separate console session that is not the API key. |
| 5 | **DNS pinning for the feed fetch** | The feed address must be public https, with no credentials and no redirects; the host name is checked at fetch time. The name is resolved once for the check and once by the HTTP client, so DNS rebinding is possible in principle. | Resolve once, connect to that address, and pin it for the request; run the fetch from a network with no route to internal addresses. |
| 6 | **Secrets management and signing-key rotation** | Secrets live in `.env` (gitignored). `LANDFALL_SIGNING_KEY` signs quotes (HMAC, 30 minute expiry); if unset the process uses a random key that is lost at restart. | A secrets manager, no `.env` on the server, a key id in each quote token so the signing key can rotate with an overlap, and separate keys per environment. |
| 7 | **Audit and logging review** | Decisions, feed syncs, quote verifications and assistant exchanges are written to the audit table. | Review what is logged (no keys, tokens, order payloads or personal data), set retention, make the audit log append-only and exportable, and alert on failed verifications. |
| 8 | **The delivered-duty-paid (DDP) remittance gap** | Landfall puts the duty into the PayPal order as tax. It does **not** collect or pay customs: the checkout total includes the duty, but remitting it to customs needs a prepaid-duty carrier or broker, which is simulated in the demo. | A real remittance partner and a reconciliation of duty collected against duty paid; legal review of who is the declarant and of how the PayPal tax line is treated. |
| 9 | **PayPal partner onboarding (only if Landfall is hosted for many merchants)** | Landfall holds no PayPal credentials in the widget flow: each merchant's server fetches and captures with its own. The hosted `POST /api/orders` option uses Landfall's own sandbox app. | If Landfall ever creates or captures orders for merchants it needs PayPal's partner programme (merchant onboarding and permissions) rather than one app. The widget flow does not need this. |
| 10 | **Quote verification limits** | `POST /api/quotes/verify` checks the signed quote against the PayPal order (amounts, tax total, per-item tax, currency). | Bind a quote to one order id and refuse a second capture, add replay protection and a per-merchant verify rate limit. |
| 11 | **Dependency and supply chain** | A licence gate runs in CI (permissive licences only). | Add dependency vulnerability scanning, pinned lock files for every app, signed images and a reviewed base image. |

## What is already enforced

- A merchant's secret key never reaches a browser: the widget uses a publishable, quote-only key; Kiln's server holds the secret and its own PayPal credentials.
- Every route is scoped to the key's shop; another merchant's ids are unknown to it.
- Checkout makes no model call. The AI only recommends; the seller accepts or overrides.
- The feed fetch refuses private, loopback and link-local hosts, credentials in the URL, redirects, and large bodies.
- Kiln's connection box (mock merchant) keeps the pasted secret key in a file in its own data folder (mode 0600 where the platform honours it), readable only by staff routes that return a prefix and the public publishable key, never the secret; it checks the key with Landfall before saving. A real merchant keeps this in its own secret store; Kiln's file is a mock's stand-in.
- A shared passport link (`/api/passport/shared/{shop}`) is public by design and returns badge facts only (level, stamps, headline), never products, prices, keys or orders.
- A passport stamp from the widget flow is earned when the merchant's server verifies an approved order, not when it captures: a verified order that is never captured still counts (item 10 lists binding a quote to one order).
