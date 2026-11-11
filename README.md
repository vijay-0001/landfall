# Landfall

**Your parcel lands. Nothing to pay at the door.**

Landfall is an AI agent for cross-border PayPal sellers. It recommends a customs code and country of origin for each product; the seller accepts or overrides. The merchant's checkout then asks Landfall for the duty, and Landfall puts it into the PayPal order as tax. The buyer sees import duty as its own line in the PayPal order, pays it up front, and receives the parcel with nothing to pay at the door. The seller sees the AI's recommendation for each product, accepts or overrides it once, and every order after that is priced from a dated, sourced register of official tariff rules.

PayPal AI Hackathon entry by Unisongroup. Everything runs against sandboxes (PayPal, Easyship test mode). **To install and run it, see [INSTALL.md](INSTALL.md).**

## What Landfall is, and what it is not

Landfall is **an AI agent for cross-border PayPal sellers**. It recommends a customs code and country of origin for each product; the seller accepts or overrides (low-confidence items are flagged and held for the seller's review, and nothing is priced duty-paid until accepted). The merchant's checkout then gets the duty from Landfall's quote and puts it into the PayPal order as tax (`amount.breakdown.tax_total` plus per-item `tax`, exact to the cent), so the buyer pays one price and owes nothing at the door. It is not a storefront and not a plugin.

**Landfall holds no PayPal credentials in this flow.** The merchant keeps its own PayPal app and secret.

1. **Connect the product feed.** The merchant's staff give Landfall the store's product feed (a Shopify-style `/products.json`). Landfall **syncs it every night** (03:00 UTC) and on demand: a new SKU gets a recommendation, a price change is picked up, a changed title or description sends the product back to the seller for review, a SKU that leaves the feed stops being sold.
2. **Add the widget to the checkout page.** One script (`GET /api/widget/landfall.js`) with a **publishable, quote-only key** and the merchant's **public** PayPal client ID.
3. **The widget asks Landfall for the quote** (`POST /api/quote`, header `X-Landfall-Key`), shows the duty line and the total, re-quotes when the cart or the country changes and again at click time, and renders the PayPal button through PayPal's own JS SDK. The PayPal order is built from the quote's `paypal_purchase_unit`. After the buyer approves, **no money has moved**.
4. **The merchant's server validates, then captures.** The widget calls the merchant's own endpoint (Kiln: `POST /api/validate`). That server fetches the approved order from PayPal with its own credentials, calls `POST /api/quotes/verify` (secret key) with the signed `quote_token` and the order, and **captures only if it matches**. A mismatch means no capture, and the buyer sees "the price changed, review the new total".
5. Landfall does not need to know about payments. The shipment hand-off and Passport stamps depend on a capture Landfall sees, so in this flow they are optional.

**Kiln & Co.** (`apps/kiln`) is a **mock merchant**: a separate small shop with its own catalogue, cart, server, **back office** (add products and upload photos at `/admin`, local only) and PayPal credentials. The merchant manages products in Kiln; Landfall only reads Kiln's product feed. It is the worked example, and its checkout page shows every call (the panel "How Landfall is used here"). The hosted `POST /api/orders` and `POST /api/orders/{id}/capture` (Landfall creates the order under its own sandbox app) still exist as an option for a merchant with no PayPal integration.

What Landfall does not do: run the merchant's storefront or cart, pay duty to customs (a carrier or broker does; simulated here), convert currency (PayPal does), or give customs or legal advice (the AI recommends; the seller declares).

**Product photos.** A product has up to four photo addresses, from the feed's `images[].src` or typed into the console's Add product form. When a recommendation is made the AI (Haiku vision) reads each photo **once** for text printed on the product's own label, tag or packaging, a country named as the place of manufacture, and visible materials. **Landfall keeps the addresses and the text that was read, never the image**: the photo is fetched (public https only, no redirects, 5 MB cap, type checked from the file's bytes), sent to the model and dropped. The seller sees what was read beside the recommendation ("What the AI read in your photos"), and the text is weighed as evidence, never obeyed. A photo that cannot be fetched or read is shown with a plain reason and never blocks a recommendation. In the feed sync, a new SKU's photos are read with its recommendation; changed photos on a product that had photos send it back to review like a changed description; photos added to a product that had none are stored without undoing the seller's decision. **Not built:** reading photos the seller uploads from their computer (links only), and a check that a photo's content changed behind an unchanged link.

**Not built, said plainly:** the **Shopify and WooCommerce** apps or plugins. They are the adoption path, not part of this build. The merchant adds the widget script and one server endpoint today. Merchant accounts have no real login (the API key is the credential), and the items in `docs/security-v1.md` are not done. No post-review accuracy is measured: the accuracy figures below are the AI's raw recommendations, before any seller review.

## The problem

A UK shop sells a £30 mug to a buyer in New York. Today the buyer is billed duty and a carrier fee at the door, often refuses the parcel, and the seller loses the sale and the mug. Sellers who try to prepay duty rely on a carrier's default customs code. Easyship's default 6-digit code for our demo mug picks the 28% hotel-and-restaurant-ware line and quotes $14.44 of duty on a $38 mug. The correct line is 10% general plus 10% Section 301 for UK origin: **20%, $7.60**. That gap is the product's pitch.

## What it does

- **Checkout.** Duty goes into the PayPal order as `amount.breakdown.tax_total` and per-item `tax`, so the buyer's PayPal receipt shows it as tax. Checkout reads the rate register only. It makes no model call. Verified on real sandbox orders: demo mug UK to US is $38 item + $14 shipping + $7.60 duty = **$59.60**, captured and shown on the receipt.
- **Recommendation, not ruling.** Haiku proposes a customs code and an origin with its reasons and sources. The seller clicks Accept or Override against versioned fine print. Evidence upload is optional. The AI carries no risk and never decides.
- **Ask only when it matters.** The seller is asked only on triggers T1 to T6 (a price-relevant ambiguity, contradictory signals, a transformed product, an origin-specific list, regulated goods, a low-value limit). At most 4 questions per product; swipe cards on a phone, a form on a desktop.
- **China origin.** Priced from 24 Feb 2026 from the official HTS Chapter 99, read as text: legacy Section 301 Lists 1 to 3 (25%) and 4A (7.5%) by line, the 12.5% Section 301 action (heading 9903.05.31, from 24 Jul 2026), the Section 122 surcharge in its window. A line that has a product exclusion in force is not priced. Earlier China history (the 2025 emergency tariffs) is not curated, and the IEEPA end date (24 Feb 2026) is an assumption from EO 14389. Not broker-verified.
- **Rate register.** Bitemporal (valid time and known time), append-only, every row cites its source (USITC HTS, UK Trade Tariff, EU TEDB, Federal Register). Every order locks the register version it was priced from, so any price can be replayed.
- **No currency conversion by us.** PayPal does FX.
- **Engagement that never rewards declaring less duty.** Tariff Time Machine (what a buyer would have paid, month by month, with a share image), Passport Stamps, Rule Radar (upcoming rule changes, with Absorb it or Pass it on). Absorb it is a seller-funded PayPal discount line that leaves `tax_total` untouched.
- **Ops.** A poller reads Federal Register notices and drafts rule proposals with Haiku. A field survives only if its supporting quote is verbatim in the notice and contains the value. People approve, edit or reject; each action is audited.
- **Shipment.** On capture, an Easyship UK to US DDP shipment is created. It never buys a label, and a failure never undoes a capture.

## Scope today (honest)

- **Products:** any product in the US tariff, found by a heading-first step over the whole tariff (1,228 headings), then priced from lines that are a plain percentage or Free (about 89% of lines). Compound and specific rates (most food, tobacco, fuels, watches) are said to be "not priced". Section 232 goods (metals, machinery, electronics, vehicles, furniture, pharma, timber) are refused as "not priced" rather than priced without those duties. Goods that cannot be handled for legal, safety or moral reasons (radioactive, weapons, drugs, protected wildlife, human remains, stolen, counterfeit) are refused with the reason and cannot be sold through the checkout.
- **Origins priced for a US buyer:** UK, EU (27), India, China (whole tariff), Vietnam, Türkiye, Thailand, Indonesia, Bangladesh, Pakistan, Japan, South Korea. Canada and Mexico are refused with a reason (USMCA treatment is not known). The country duties and exemption lists of U.S. note 52 are read from the official Chapter 99 text.
- **Destinations:** US, UK, the 27 EU states (flat 3 euro per item under 150 euros plus VAT by member state), Australia (no duty at or below AUD 1,000, 10% GST; the 5% rate is from the product decision and needs a broker check). **Canada is not built.**
- **Buyer storefront** (`/shop`): any accepted product, quantity and ship-to country, one cart, PayPal sandbox checkout, receipt after capture. A product that cannot be priced never takes the others down.
- **Help me find it:** when no code is found or the band is not High, official search links (USITC HTS, CBP CROSS, UK Trade Tariff, EU TARIC) with the listing's words filled in; the seller can then Override with a typed code that is checked against the register.
- **Assistant:** a small box on the product page (Haiku only) that explains, says what would change the answer and points to sources. It refuses to decide, to help pay less than is due, and to follow instructions hidden in a question; every exchange is stored.

## Architecture

One VPS, Docker Compose: `web` (Next.js, React, TypeScript, TanStack Table, Recharts), `api` (FastAPI, Pydantic, SQLAlchemy), `worker` (APScheduler: nightly sync and rule drafts), `renderer` (Playwright: share images), `db` (PostgreSQL), and Caddy. See `docs/architecture.md` and `docs/hld.md`.

Reusable packages (separate on purpose, published names use `landfall-pay`): `packages/register` (bitemporal register and loaders), `packages/engine` (pure duty engine, Decimal), `packages/classifier` (closed candidate list, two independent calls, rule-set bands), `packages/paypal` (order with duty as tax, capture), `packages/rules`, `packages/shipping`.

Rules the design depends on: the model is **Haiku only** (`claude-haiku-5-5`, thinking disabled); the model never prices anything; confidence bands are set by rules, not by a model score; a failed source changes nothing and a stale source degrades to a visible note and then a pause.

## Evidence it works (Sprint 0 gate)

`spikes/GATE_LOG.md` records each dependency proven before building: PayPal sandbox order with duty as a tax line (captured, receipt screenshot), USITC HTS, Federal Register, UK Trade Tariff, EU VAT (TEDB, SOAP), Claude classifier latency and cost, Easyship DDP quote and shipment, Shippo test mode. Recorded API responses live in `spikes/*/fixtures` and in the package fixtures; tests never touch the live internet.

A live sandbox run on 3 Nov 2026: order created, approved by the sandbox buyer in Chrome, captured (`COMPLETED`, $59.60 gross, `tax_total` $7.60, PayPal fee $2.62 charged on the full amount including duty), one passport stamp minted, Easyship DDP shipment created, no label bought. A second run on 10 Nov 2026 with the sandbox buyer approving (mug x1, mug x3, a two-origin cart; a fourth order was cancelled at PayPal) was read back from PayPal's own order records for the first three: see `docs/test-report.md`.

## Accuracy: what we measured, and how

Read this table with the method in mind. **Reference labels are written by an independent reviewer agent working blind** (it saw only the listing text and the official HTS text, never our code or results). They are **not broker-verified**. Where the listing does not say a deciding fact (knitted or woven, napped or not), the reviewer's label is itself a judgement. Seller text is not republished: listing text stays local; labels and links are in git (`spikes/d13_real_listings`, `d14_fresh_listings`, `d15_fresh_batch3`).

"Duty" compares the duty our pipeline would charge, at a $40 reference price, with the duty on the reviewer's national line. "Untuned" means the classifier was frozen before the labels were seen.

| Set | Listings | In scope | 6-digit exact (in scope) | Duty exact | Duty within $1 | Notes |
|---|---|---|---|---|---|---|
| 200 draft listings (drafted, Claude-labelled, Haiku-audited) | 200 | 200 | 90.0% | not measured | not measured | an early harness check on drafted, not real-shop, text with a 144-code list (the Sprint 0 spike scored 96.5% to 97.5% on a 38-code list: a smaller list is easier) |
| 108 real shop listings (tuned on) | 108 | 83 | 74.7% | 70.7% | 89.0% | the national-line step was developed on this set; treat as optimistic |
| 69 real listings, 9 other shops (used for harness changes) | 69 | 56 | 64.3% | 56.0% | 68.0% | used to decide the wider closed list; not a clean test |
| **38 fresh listings over the WIDE tariff (toys, kitchen appliances, hair accessories; blind labels; 4 Nov)** | 38 | 38 | **60.5%** (heading 71.1%; clear listings 92.3%; labels the reviewer was sure of 91.7%) | 53.8% (13 priced) | 61.5% | whole-tariff heading-first classifier, 0 model failures, 1.0 questions per product, 6 High-band listings all exactly right, about $0.025 per product; **small sample from 4 shops, read as a range not a result** |
| **94 real listings, never seen (untuned)** | 94 | 85 | **72.9%** | **71.6%** | **84.0%** | frozen classifier, same shop families, new products; the headline number |

**Run-to-run noise is about 3 to 7 points.** The same frozen pipeline on the same 94 listings scored 69.4% / 64.6% / 79.3% (6-digit in scope / duty exact / within $1) in one run and 72.9% / 71.6% / 84.0% in a second run made after China rows were added to the register (the model's answers at the margin move between runs; the register change affects only which questions are asked). Read the headline as "roughly 70% exact, roughly 80% to 85% within $1", not as a precise figure.

What these numbers mean for the product:

- The seller always confirms. On the untuned set the pipeline asked **1.4 questions per product on average**, and no listing reached the High band in the second run and 1 of 94 in the first, so bulk accept is a small convenience, not the main path. On the 108-listing set 13 listings were High band and 12 were exactly right on the 6-digit code; across the three real-listing sets 14 of the 15 High-band listings were exact on the 6-digit code (small numbers).
- "Automated" is not "always right": listings where both calls agreed, no deciding fact was missing and no line question was needed (16 on the 108 set and 7 on the untuned set in the first run; 14 and 6 in the second) had a duty error in 2 of 16 and 2 of 7 in the first run and none in the second. Treat them as usually right, not as guaranteed. Because the seller confirms every product, these are caught by the seller's own accept, but the claim is "the AI recommends", never "the AI is right".
- The wider closed list (282 six-digit subheadings, all of chapters 61 and 62 plus made-ups) did not hurt the core: on the 73 in-scope listings whose labels did not change, 6-digit exact went from 83.6% to 82.2%, duty exact from 74.6% to 76.7%, within $1 from 88.7% to 86.3% (narrow 144-code list against the wide list, same listings).
- The right code is the final answer or the runner-up on about 82% of untuned listings, which is why asking the seller beats guessing.
- Items outside the closed list (food, glass, plastics, metal) are paused, not guessed: 66.7% of the 9 out-of-scope items in the untuned set (a small sample).
- Cost and speed: about 4.5 Haiku calls per new product, about **$0.012 per product** at an assumed $1/$5 per million tokens (list price to be confirmed; about 97% of input tokens are cache reads), p95 about 3 s per call. Checkout makes none.

Known weaknesses, stated plainly: apparel is the hardest area (knitted against woven, men's against women's headings are often not stated by sellers); the national-line step needs the seller's answer on many listings; on the wide tariff the first step sometimes picks the wrong heading (a product named for its function but defined by its material), which one retry pass partly fixes; only 13 of 38 wide listings ended up priced because many are Section 232 or compound-rate goods; origins other than the fourteen above are not priced (the product says so instead of guessing). Reproduce with `tools/accuracy_run.py`; raw results are in `docs/accuracy/`.

## Tools used (for the judges)

- **PayPal:** Orders v2 on the free sandbox, through PayPal's JS SDK (the widget renders the PayPal button) and the merchant's own server (fetch the approved order, capture). Duty is sent as `amount.breakdown.tax_total` plus per-item `tax` (split to the cent), so the buyer's PayPal receipt shows it as tax. Create, approve, validate, capture. PayPal does the currency conversion. We read the fee PayPal charges (on the full amount, duty included) and show it on the seller pricing screen.
- **AI:** Claude Haiku 5.5 (`claude-haiku-5-5`, thinking disabled), and only Haiku. It reads a product listing and its photos (labels, made-in text, materials) and recommends a code and origin; it explains itself in a small assistant box; it drafts rule changes from Federal Register notices for people to approve. It never prices anything, never decides, and is not called at checkout. Confidence bands are set by rules, not by the model.
- **Easyship (test mode):** a delivered-duty-paid shipment record after capture. No label is bought and no customs duty is paid.
- **Not used:** PayPal FX as a Service (needs a contract), any PayPal agent toolkit.

## Coverage and sources

Shown in the console page "Coverage and sources" (linked from Kiln's footer) and served by `GET /api/coverage`. Only what is covered today is listed; everything else is left out on purpose, and a disclaimer says adding more countries and kinds of goods is planned for a later phase (Phase 2).

**Covered today (goods made in, shipped to):**

| Goods made in | United States | United Kingdom | European Union (27 states) | Australia* |
|---|:-:|:-:|:-:|:-:|
| Bangladesh, China, European Union, India, Indonesia, Japan, Pakistan, South Korea, Thailand, Türkiye, United Kingdom, Vietnam | ✓ | ✓ | ✓ | ✓ |

The origins are read from the register. Duty for the UK, the EU and Australia does not depend on where the goods were made, so every covered origin is covered for every covered destination. * Australia is a hand-curated table, to be confirmed by a customs broker before real use.

**Where the rates come from:**

| Source | What it provides | Refreshed |
|---|---|---|
| US tariff schedule (USITC) | US duty rates per tariff line | Every night, 02:00 UTC |
| UK Trade Tariff | UK duty and VAT per commodity code | Every night, 02:00 UTC |
| EU VAT rates (TEDB) | VAT for each of the 27 member states | Every night, 02:00 UTC |
| Federal Register notices | New US tariff notices; a person approves each proposed rule | Every night, 02:00 UTC |
| Australia (curated table) | 5% duty above AUD 1,000 and 10% GST | By hand: not refreshed automatically |

The cadence is the worker's real schedule (`apps/worker/landfall_worker/main.py`): one job at 02:00 UTC runs the four automatic sources in turn, plus one pass at start-up if the last good run is over 24 hours old; each connected shop's product feed is re-read at 03:00 UTC. With no good refresh for 48 hours checkout shows "rates last updated" for that destination; after 7 days duties-included is paused there.

## Install and run

**Full steps are in [INSTALL.md](INSTALL.md)**: what you need, the `.env` settings, two ways to start it (all in containers, or local development), a five-minute walk through the demo, how to run the tests, and troubleshooting.

In short: you need Docker, and three things of your own that are not in the repository, an `ANTHROPIC_API_KEY`, a PayPal sandbox app (client id and secret), and a PayPal sandbox buyer account to approve the test payment. Credentials live only in `.env`, which git ignores.

```bash
cp .env.example .env     # then fill it in, see INSTALL.md
docker compose -f infra/docker-compose.yml --env-file .env --profile standalone up -d --build
```

Then open the console at http://localhost and the mock shop at http://kiln.localhost. Deploying behind an existing reverse proxy: `infra/vps-deploy.md`.

## Licences

Landfall is released under the **Apache License 2.0** (`LICENSE`, `NOTICE`). Third-party components keep their own licences.

Every dependency is permissive (MIT, Apache-2.0, BSD, ISC) or a reviewed, listed exception (`licences/exceptions.json`: certifi MPL-2.0, axe-core and its Playwright wrapper MPL-2.0 as test-only tools, lightningcss MPL-2.0 as a build tool, caniuse-lite CC-BY-4.0 data, three SIL OFL fonts, a local stub in place of sharp's LGPL binaries). `scripts/ci licences` fails the build on GPL, AGPL, SSPL, BSL or commercial-only packages; `scripts/prove_licence_gate.sh` plants a GPL package in both ecosystems and shows the gate fail.

## Repo map

`apps/web`, `apps/api`, `apps/worker`, `apps/renderer`, `packages/*`, `infra/` (compose, Caddyfile, VPS notes, backup), `spikes/` (recorded API responses and the evaluation set), `docs/` (architecture, high-level design, security notes, logos), `tools/` (data fetchers), `tests/`.

## Photo credits
Kiln & Co.'s product photographs are real photographs from Unsplash (two per product), used under the Unsplash License and downloaded through the Unsplash API; the credits, with each photographer and photo page, are in `apps/kiln/public/photos/CREDITS.md` (also served by Kiln at `/photos/CREDITS.md`). A photo shows a kind of product, not the exact one described, so they are stand-ins for a merchant's own product photography.
