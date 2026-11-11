# Landfall HLD

High-level design for duties-included checkout for PayPal sellers · Oct 29, 2026

## 1. Summary and design principles

Landfall lets a small cross-border PayPal seller charge import duty at checkout so the buyer pays nothing at the door. The AI recommends a customs code, origin and duty per destination; the seller accepts or overrides; a daily-synced, effective-dated rate register prices every order; PayPal collects the duty as tax. Requirements are in the [BRD](https://claude.ai/artifact/SStV7qJDSCGAXoEv9mz1vB); screens are on the [mockups canvas](https://claude.ai/artifact/C7Pke7dp5hUvkGRJduyxZi); source research is in the [automation and feasibility design](https://claude.ai/artifact/RNpMFSK8p1G6FLfnvm7VC9).

**Principles**

1.  **The AI helps; the seller decides.** Every recommendation is a proposal with reasons and sources. Nothing reaches a buyer until the seller has accepted or overridden it.

2.  **No model call at checkout.** Checkout reads only accepted classifications and the register. It is fast, deterministic and auditable.

3.  **Time is a first-class field.** Every rate row carries when it is valid and when we learned it. Every order locks the register version it used.

4.  **Ask only when it changes the price.** Questions to the seller fire only on the triggers T1 to T6.

5.  **Official sources only, with provenance.** Each rate links back to the document it came from.

6.  **Permissive licences, reusable packages.** Register, classifier and PayPal adapter ship as separate packages for reuse in later work.

## 2. Architecture overview

[image omitted]

DutyPass architecture · 4 screens, 1 API, 1 database

One Next.js front end serves four screens. One FastAPI service holds four modules. Postgres holds the register, catalogue, orders and audit log. The model is called only at listing time and when drafting rules from notices; checkout never waits on it. The rate register is the centre: every price shown to a buyer is a read from it at a stated date.

## 3. Components and responsibilities

| Component             | Responsibility                                                                                                           | Talks to                                                | Owns                              |
|-----------------------|--------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------|-----------------------------------|
| Web app (Next.js)     | Seller app, buyer checkout widget, public Time Machine, ops console. Tables use TanStack Table.                          | API only                                                | No data of its own                |
| Recommender           | Classify code and origin, run triggers, produce questions, save accept or override.                                      | Claude API, register (read), catalogue                  | Recommendations, questions        |
| Duty engine (library) | Pure function: product decision + destination + value + date + register version → duty and tax with a calculation trail. | Register (read)                                         | Nothing; stateless                |
| Checkout              | Quote landed cost, create and capture PayPal order, lock register version, write parcel export.                          | Duty engine, PayPal Orders API                          | Orders                            |
| Engagement            | Passport stamps and levels, Radar alerts per seller, Time Machine price series.                                          | Duty engine, register, orders                           | Stamps, alerts                    |
| Rules and ops         | Queue of AI-proposed rules from notices; approve, edit, reject; publish register versions.                               | Claude API, register                                    | Rule proposals, register versions |
| Sync workers          | Nightly pull from each official source, diff against the last load, write new rows, record source health.                | USITC, Federal Register, TARIC, UK Trade Tariff, EU VAT | Raw source snapshots              |
| Postgres              | Register, catalogue, orders, audit log.                                                                                  | All services                                            | All persistent data               |

## 4. Listing-time pipeline

Runs when a product is added or edited, never at checkout.

1.  **Normalise.** Title, description, photos, materials, shop country, any "made in" text. Hash the inputs; identical listings reuse the last result.

2.  **Classify the code.** Two independent Claude calls with different prompts propose a 6-digit code with the legal text they relied on. A retrieval step supplies candidate headings and explanatory notes from the register, so the model chooses among real codes rather than inventing one. National 8 or 10-digit codes are then picked per destination from the register's children of that 6-digit code.

3.  **Propose origin.** Signals are scored separately: label photo text, listing text, shop history, "handmade" claims, supplier hints, and shop country as the weakest default. Shop country is never assumed to be origin when any other signal disagrees.

4.  **Band.** High if both calls agree at 6 digits and no origin signals conflict; Check if they disagree at 8 or 10 digits only; Ask if a trigger fires.

5.  **Triggers.** T1 price-relevant ambiguity (the two candidate answers differ by more than the larger of \$1 or 3% of buyer price); T2 contradiction between signals; T3 seller transformed the product; T4 origin on an origin-specific list; T5 regulated goods (duties-included paused); T6 value above a low-value limit. Each trigger yields at most one question, four per product in total, each carrying the price impact per answer.

6.  **Price.** The duty engine prices each destination at today's expected import date.

7.  **Seller decides.** Accept or Override, with the fine-print version stored. Evidence is optional. Only Accepted or Overridden products are eligible for duties-included.

8.  **Record.** Model id, prompt version, inputs hash, sources, register version, band, triggers, answers and decision go to the audit log.

Re-classification happens only when the listing changes or ops withdraws a code; a rate change does not re-run the model, it only re-prices.

## 5. Rate register

The register answers one question: *what rate applied to this code, from this origin, into this destination, on this date, as we knew it at that time?* It is bitemporal.

| Field                      | Meaning                                                                                         |
|----------------------------|-------------------------------------------------------------------------------------------------|
| destination                | US, EU, GB                                                                                      |
| code                       | 6 to 10-digit national code, or a pattern such as 4202.\* for rules                             |
| origin_scope               | All, a single country, or a named list (for example the Section 301 list)                       |
| measure                    | base_duty, additional_duty, import_vat, flat_per_line (EU €3), low_value_relief                 |
| rate                       | Percent, fixed amount, or amount per unit, with currency                                        |
| valid_from, valid_to       | When the law says it applies (valid_to open for current rows)                                   |
| recorded_at, superseded_at | When we learned it and when a later load replaced it                                            |
| source_ref                 | Document id and URL (HTS release, Federal Register citation, TARIC measure id, UK commodity id) |
| register_version           | The nightly or ops-published version that introduced the row                                    |

**Reading rules**

- Checkout reads with valid date = expected import date (US uses arrival date) and known date = now.

- Time Machine reads valid date = the slider date and known date = now, so history shows what applied, corrected if we later learned better.

- Replaying an old order reads with known date = the order's locked register version, so it reproduces exactly what the buyer was charged.

- A future-dated row (announced change) is just a row with valid_from in the future; Radar lists them.

- Rows are never updated in place; corrections close the old row (superseded_at) and add a new one.

## 6. Daily sync and ops review

| Source                | Method                                                                      | Change detection                                        | Publish path                                                          |
|-----------------------|-----------------------------------------------------------------------------|---------------------------------------------------------|-----------------------------------------------------------------------|
| USITC HTS (US)        | REST exportList per chapter in scope                                        | Compare against last snapshot by code and field         | Automatic for general and special columns; Chapter 99 lines go to ops |
| Federal Register (US) | Documents API filtered by CBP, USTR and tariff terms                        | New document ids                                        | Claude drafts a rule; ops approves, edits or rejects                  |
| CBP CSMS (US)         | Email subscription parsed into the ops queue                                | New message                                             | Ops only                                                              |
| EU TARIC              | Commission daily file; fallback Swedish Customs daily-diff XML              | File's own diff                                         | Automatic for third-country duty measures in scope                    |
| EU VAT rates          | TEDB web service                                                            | Rate and date change                                    | Automatic                                                             |
| UK Trade Tariff       | REST commodity endpoints for codes in scope, throttled under the rate limit | Compare against our stored history (no as-of parameter) | Automatic                                                             |

**Run order:** fetch → store raw snapshot → diff → write candidate rows → validate (no negative rates, no gaps or overlaps in validity for the same key, codes exist) → publish as a new register version, or hold for ops if validation fails or the source is legal text.

**Health:** each source records last success. 48 hours without success shows "rates last updated" at checkout for that destination; 7 days pauses duties-included there. Ops sees both on the sync table.

**AI-proposed rules:** Claude reads the notice and fills a fixed rule form (destination, code pattern, origin scope, measure, rate, valid_from, valid_to, quoted sentence). It must quote the sentence each field came from; a field with no quote stays blank for ops. Approving writes a future-dated row and triggers Radar alerts to affected sellers.

## 7. Duty engine

A pure, deterministic library shared by checkout, Time Machine and Radar. Same inputs always give the same output.

**Input:** accepted code and origin, destination, customs value (item price, plus shipping where the destination's rules add it), quantity, expected import date, register version.

**Steps**

1.  Collect every row matching code, origin and destination that is valid on the import date in the given version.

2.  Apply low-value rules first: UK £135 relief (duty only), EU flat €3 per item line for IOSS consignments under €150, US no de minimis.

3.  Add base duty, then additional duties in the order the law stacks them, honouring caps where a rule says "the higher of" or "capped at".

4.  Add import VAT where the destination charges it at sale (EU via IOSS, UK seller-collected).

5.  If the import date falls within a set number of days of a change date (configurable per destination, start with 5 days), price both sides and use the higher.

6.  Round per the destination's rule and return the amount plus a calculation trail: each row used, its source and the arithmetic.

**Out of scope for the engine:** currency conversion (prices arrive in the buyer's currency), carrier fees, and anything needing a model call.

## 8. PayPal integration

**Order creation.** Checkout calls the Orders v2 API with intent CAPTURE. The purchase unit's amount.breakdown carries item_total, shipping and tax_total; duty and import tax go into tax_total because the API has no duty field. Each item also carries its own tax so the receipt shows it per line. The order's custom_id holds the Landfall order id, and the register version is stored on our side.

**Capture.** On approval we capture, store the PayPal capture id, and write the parcel export (declared code, origin, value, duty collected) for the shipping partner. In the demo, Easyship's free API quotes the UK to US shipment with duties prepaid (DDP, FedEx) and creates the shipment record; we compare its duty line with our own engine. Shippo test mode is the backup for labels (DDP works there from a US origin only). Both are self-serve; no partner agreement is needed. No label is bought, because that spends real money on Easyship.

**Currency.** Landfall never converts currency. For the hackathon the seller sets a price per currency in the catalogue and the engine works in that currency. After the hackathon, if PayPal grants access, FX as a Service returns an fx_id that we pass into the order as the payee receivable rate id; the rate is PayPal's, not ours.

**Refunds and returns.** A full refund returns duty with the item, since it sits in the order total. Recovering duty already paid to customs is the shipping partner's process and is out of scope for the hackathon.

**Sandbox only** for the hackathon; no live credentials, no card data touches Landfall.

**Sandbox test result (30 Oct).** An order with item_total, shipping and tax_total was approved and captured, and the buyer receipt shows the duty as its own Tax line. A UK business seller received US dollars and PayPal converted them to pounds itself. PayPal's fee was charged on the full amount including the duty, so the seller pays a processing fee on duty they collect; the seller pricing screen shows it. Sandbox accounts must be a UK business seller and a US personal buyer: accounts registered in India cannot take US dollars.

## 9. Engagement features design

| Feature             | How it works                                                                                                                                                                                                                                     | Data it reads            | Guardrail in code                                                                                  |
|---------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------|----------------------------------------------------------------------------------------------------|
| Tariff Time Machine | Precomputed monthly series per (product template, origin, destination) from Jan 2025, plus every change date as an extra point. The slider snaps to points; share renders a server-side PNG with source footnotes. Cached at the edge; no login. | Register via duty engine | Series built only from published register versions; a banner shows when any point is illustrative. |
| Passport Stamps     | A stamp is minted on the first captured duties-included order to a destination. Levels count products reviewed and duty-paid orders shipped. Badge is an SVG rendered from the seller's stamps.                                                  | Orders, catalogue        | Scoring function has no input for duty amount or override direction.                               |
| Rule Radar          | On register publish, find future-dated rows, match them to sellers' accepted products, price both sides with the engine, and create an alert with days remaining and impact per order. Absorb or Pass it on writes a scheduled price change.     | Register, catalogue      | Only ops-approved or automatic rows from official sources create alerts.                           |
| Swipe interview     | Renders the questions from the pipeline as cards; each answer re-prices live. Falls back to a form on desktop.                                                                                                                                   | Recommender              | Same questions and limits as the form; no extra prompts.                                           |

## 10. Data model and interfaces

**Main tables**

| Table            | Key fields                                                                                                                     |
|------------------|--------------------------------------------------------------------------------------------------------------------------------|
| shop             | id, name, country, paypal_merchant_id, ioss_registered                                                                         |
| product          | id, shop_id, title, description, photos, price_by_currency, inputs_hash                                                        |
| recommendation   | id, product_id, destination, code, origin, band, triggers, reasons, sources, model, prompt_version, register_version           |
| decision         | id, recommendation_id, action (accepted, overridden), code, origin, fine_print_version, evidence_ref (optional), user_id, at   |
| rate_row         | see section 5                                                                                                                  |
| register_version | id, published_at, source_runs, published_by (system or ops user)                                                               |
| rule_proposal    | id, notice_ref, fields with quoted sentences, status, reviewer                                                                 |
| order            | id, shop_id, paypal_order_id, capture_id, destination, currency, item_total, shipping, duty_tax, register_version, import_date |
| stamp, alert     | seller engagement records                                                                                                      |
| audit_event      | append-only log of every write above                                                                                           |

**API surface (FastAPI, JSON)**

| Endpoint                                                  | Purpose                                                          |
|-----------------------------------------------------------|------------------------------------------------------------------|
| POST /products, POST /products/{id}/recommend             | Add a product; run the pipeline                                  |
| POST /recommendations/{id}/answer                         | Answer a question; returns re-priced result                      |
| POST /recommendations/{id}/decision                       | Accept or override, with fine-print version                      |
| POST /quote                                               | Landed cost for a cart and destination (no model call)           |
| POST /orders, POST /orders/{id}/capture                   | Create and capture the PayPal order                              |
| GET /register/rate                                        | Rate lookup by code, origin, destination, valid date, known date |
| GET /timemachine/series                                   | Public price series                                              |
| GET /radar, POST /radar/{id}/choice                       | Seller alerts and Absorb or Pass-it-on                           |
| GET /ops/sync, POST /ops/rules/{id}/{approve,edit,reject} | Ops console                                                      |

The register and duty engine are published as their own packages (landfall-register, landfall-engine) with no dependency on the web app, so they can be reused.

## 11. Security, compliance and the AI's role

**The AI's role, enforced in design**

- No path lets a recommendation reach checkout without a seller decision row.

- Fine-print text is versioned; each decision stores the version the seller saw.

- Evidence upload exists but no code path requires it.

- Product copy and API responses call the output a recommendation, never a classification ruling.

- Landfall is not the importer, broker or payer of customs; the shipping partner files and pays.

**Security**

- Secrets (PayPal client secret, Claude key) in a secrets store, never in the repo or front end.

- PayPal webhooks verified by signature before any order state changes.

- Per-shop row scoping enforced in the API layer and by Postgres row-level security.

- Ops actions require a separate role and are written to the audit log.

- Uploaded evidence and label photos stored privately with short-lived links.

**Privacy:** buyer name and address stay with PayPal and the shipping partner; Landfall keeps destination country and postcode only. Listing text sent to Claude contains product data only.

**Model safety:** prompts treat listing text and notices as data; the rule proposer can only fill the fixed form and must quote its source sentence; nothing the model returns is published without validation or a person.

## 12. Stack, deployment and licences

| Layer                    | Choice                                                                                                            | Licence                                    |
|--------------------------|-------------------------------------------------------------------------------------------------------------------|--------------------------------------------|
| Front end                | Next.js, React, TypeScript                                                                                        | MIT                                        |
| Tables                   | TanStack Table                                                                                                    | MIT                                        |
| Charts                   | Recharts                                                                                                          | MIT                                        |
| API                      | FastAPI, Pydantic                                                                                                 | MIT                                        |
| Database                 | PostgreSQL                                                                                                        | PostgreSQL Licence (permissive)            |
| Data access              | SQLAlchemy, Alembic                                                                                               | MIT                                        |
| Jobs                     | APScheduler                                                                                                       | MIT                                        |
| HTTP and parsing         | httpx (BSD-3), lxml (BSD-3), openpyxl (MIT)                                                                       | Permissive                                 |
| Share images             | Playwright headless Chromium screenshot                                                                           | Apache-2.0                                 |
| Model                    | Claude via the Anthropic Python SDK                                                                               | SDK MIT; API under commercial terms        |
| Shipments and duty quote | Easyship API (primary, UK to US DDP); Shippo (backup, US origin only)                                             | Commercial terms; called over HTTPS        |
| Payments                 | PayPal Orders v2; duty sent as tax_total and per-item tax                                                         | Commercial terms; sandbox only             |
| Hosting                  | One VPS, Docker, Docker Compose, Caddy (reverse proxy, automatic HTTPS)                                           | Apache-2.0 (Docker Engine, Compose, Caddy) |
| Data                     | US tariff data (public domain), UK tariff (Open Government Licence), EU data (Commission reuse decision 2011/833) | Reuse permitted with attribution           |

**Deployment:** everything runs on one VPS under Docker Compose as six containers: caddy (reverse proxy, automatic HTTPS), web, api, worker, renderer and db (PostgreSQL). CI builds four images (web, api, worker, renderer) and pushes them to a registry; the VPS pulls them and runs docker compose up. Only caddy exposes ports 80 and 443; every other container sits on a private network. The database lives on a named volume on the VPS disk, a nightly pg_dump is copied off the VPS, and passwords and API keys sit in a protected .env file on the server, never in images or git. The renderer needs about 1 GB of memory for Chromium, so size the VPS at 4 GB or more. Environments: local (same compose file), demo (sandbox PayPal and Easyship test mode). A licence check (pip-licenses, license-checker) runs in CI and fails the build on any copyleft or source-available licence.

## 13. Failure modes

| Failure                                     | Detection                                                       | Behaviour                                                                            |
|---------------------------------------------|-----------------------------------------------------------------|--------------------------------------------------------------------------------------|
| Source sync fails                           | Source health table                                             | 48 h: "rates last updated" note; 7 days: duties-included paused for that destination |
| Source returns malformed or suspicious data | Validation step (gaps, overlaps, negative rates, unknown codes) | Version held for ops; register stays on last good version                            |
| Claude API slow or down                     | Timeouts                                                        | Listing saved as Not yet reviewed; retry queue; checkout unaffected                  |
| The two classifier calls disagree           | Band logic                                                      | Check or Ask band; never bulk-acceptable                                             |
| PayPal order creation fails                 | API error                                                       | Buyer sees PayPal's error; no order row written                                      |
| Rate changes between quote and capture      | Locked register version on the order                            | Buyer pays the quoted amount; the order records which version                        |
| Announced change withdrawn                  | Ops edits or closes the future row                              | Radar alert updated; scheduled price changes cancelled                               |
| Product turns out to be regulated           | Trigger T5 or ops flag                                          | Duties-included paused for the product with a reason                                 |

## 14. Architecture decisions

| ADR | Decision                                                            | Why                                                                              | Alternative rejected                        |
|-----|---------------------------------------------------------------------|----------------------------------------------------------------------------------|---------------------------------------------|
| 01  | Seller accepts or overrides; AI only recommends                     | Published accuracy is far from reliable; risk stays with the party that declares | Auto-apply above a confidence score         |
| 02  | No model call at checkout                                           | Speed, determinism, audit                                                        | Classify at checkout                        |
| 03  | Bitemporal register in Postgres                                     | Answers both "what applied" and "what we knew"; supports replay and Time Machine | Latest-rate table with a history log        |
| 04  | Duty goes in tax_total                                              | Orders API has no duty field; tax shows on receipt                               | Custom line item, which inflates item_total |
| 05  | No currency conversion in Landfall                                  | PayPal owns FX; avoids regulated activity                                        | Our own FX rates                            |
| 06  | Legal notices need a person; structured feeds publish automatically | Notices are prose with legal nuance; feeds are structured                        | Fully automatic rule extraction             |
| 07  | Two independent classifier calls                                    | Cheap disagreement signal for banding                                            | Model self-reported confidence              |
| 08  | Register and engine as separate packages                            | Reuse in later hackathons and client work                                        | One monolith                                |
| 09  | TanStack Table, not AG Grid                                         | MIT licence and headless; fits commercial reuse                                  | AG Grid Enterprise                          |

## 15. Test strategy

| Level                     | What                                                                                                        | Pass bar                                                                                                                                                      |
|---------------------------|-------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Duty engine unit tests    | Golden cases per destination: US stacked duties, EU €3 per line, UK £135 relief, change-date straddle, caps | Exact to the cent                                                                                                                                             |
| Register property tests   | No overlapping validity for the same key; replay by version reproduces history                              | Zero violations                                                                                                                                               |
| Sync contract tests       | Recorded responses from each source parsed and diffed                                                       | Stable output on fixtures                                                                                                                                     |
| Classification evaluation | 200 real listings across the 3 categories, labelled by a broker                                             | Report 6-digit and full-code accuracy honestly; aim for 6-digit agreement above the published 57.5% best within our narrow scope, but publish whatever we get |
| Trigger evaluation        | Same 200 listings                                                                                           | Count questions per product; target 80% with zero questions                                                                                                   |
| PayPal sandbox end-to-end | Create, approve, capture; receipt shows tax line                                                            | Passes in CI against sandbox                                                                                                                                  |
| Accessibility             | Automated checks plus keyboard pass on all screens                                                          | WCAG 2.2 AA                                                                                                                                                   |
| Licence scan              | Every dependency                                                                                            | No copyleft or source-available licence                                                                                                                       |

Related: [BRD](https://claude.ai/artifact/SStV7qJDSCGAXoEv9mz1vB) · [mockups canvas](https://claude.ai/artifact/C7Pke7dp5hUvkGRJduyxZi) · [automation and feasibility design](https://claude.ai/artifact/RNpMFSK8p1G6FLfnvm7VC9)
