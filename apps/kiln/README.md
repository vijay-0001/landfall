# Kiln & Co. (mock merchant)

A small make-believe online shop, **separate from Landfall**. It stands in for any store that sells through PayPal. It has its own catalogue, cart and pages, and no database.

**The merchant manages its shop in Kiln, not in Landfall.** Kiln has its own back office at `/admin` (a mock with one shared staff login: user `KILN_ADMIN_USER`, default `owner`, and `KILN_ADMIN_PASSWORD`; it is **off unless a password of 10 or more characters is set**, and must never be on for a public site; shoppers need no account to buy, and shopper accounts are not built): add a product with a title, description, a price in each of four currencies (USD, GBP, EUR, AUD: the four destinations Landfall prices) and up to four uploaded photos (JPEG, PNG or WebP, 2 MB each, checked from the file's bytes), edit it, or remove it. Products live in Kiln's own catalogue file (`data/`, git-ignored) and the photos are stored on Kiln's own server; the seed catalogue is `catalogue.json`. The feed at `/products.json` follows every change, with `images[].src`. Landfall only ever sees Kiln through the feed: the merchant's staff connect it once, and Landfall syncs it every night or on "Sync now".

Its only link to Landfall is the HTTP API. Which Landfall account Kiln's checkout asks is set in the back office, under **Landfall connection**: staff paste the account's secret key (Landfall shows it once when the account is opened); Kiln checks it with a real call, keeps it on its own server (`data/landfall-connection.json`, never sent to a browser) and works out the publishable key for the checkout page. Until a key is saved, Kiln uses `LANDFALL_KILN_API_KEY` from its environment (the demo account).

| Kiln does | Landfall call |
|---|---|
| Serves its catalogue as a Shopify-style feed at `/products.json` | Landfall imports it (`POST /api/products/import`) and re-reads it every night and on Sync now |
| The checkout page loads Landfall's widget with the **publishable** key | `POST /api/quote` (header `X-Landfall-Key`): the duty, the total and a signed `quote_token`; the widget builds the PayPal order from it |
| After the buyer approves, Kiln's server fetches the order with **its own PayPal credentials** | `POST /api/quotes/verify` with the **secret** key; only if valid does Kiln capture the payment |
| Shows what Landfall holds for its products | `GET /api/catalogue` (shop badges, the panel, "Not in Landfall yet" in the admin list) |

The shop says only what Landfall has priced: a product marked **Duties included** is one the seller has accepted; others say no duty is added yet; a product Landfall has not read yet cannot be ordered until the next sync. The right-hand panel on the checkout page, **How Landfall is used here**, shows each call (request, response, time) as it happens.

Run it (Landfall's API must be up):

```
LANDFALL_API_URL=http://127.0.0.1:8000 LANDFALL_KILN_API_KEY=lf_test_... KILN_PUBLIC_URL=http://127.0.0.1:3400 node server.mjs
```

Tests: `node --test` (against a fake Landfall and a fake PayPal; the back office has its own test file, with a temporary data folder). Product photos are real photographs from Unsplash, credited in `public/photos/CREDITS.md`.
