# Landfall Sprint 0 gate log

| # | Dependency | Date | Result | Evidence | Notes |
|---|---|---|---|---|---|
| D1 | PayPal sandbox: duty carried as tax | 30 Oct 2026 | GREEN | d1_paypal/fixtures/*.json; buyer receipt screenshot (Tax $7.45) | See findings below |
| D2 | US tariff schedule (USITC HTS) | 1 Nov 2026 | GREEN | live calls from Claude workspace | Returns rates for 6912.00.* and 4202.32.*. Chapter 99 duties are legal text, so Section 301 rows stay hand-curated |
| D3 | Federal Register API | 1 Nov 2026 | GREEN | live call | Returns current notices incl. 22 Oct 2026 de minimis suspension for mail |
| D5 | UK Trade Tariff API | 1 Nov 2026 | GREEN (as_of unverified) | live call | Works with a valid 10-digit code and a browser-style user agent; as_of accepted but not yet shown to return older rates |
| D8 | Shippo test mode, DDP | 1 Nov 2026 | GREEN for US origin, AMBER for UK origin | d8_shippo/fixtures | DDP declaration VALID. US origin: DHL Express test label with tracking and electronic commercial invoice created (after DHL terms accepted); USPS label also works (needs eel_pfc NOEEI_30_37_a). UK origin: only DPD UK rates, which reject DDP; no DHL rate because the Shippo DHL account is US-based |
| D9 | Easyship API, DDP quote | 1 Nov 2026 | GREEN, with a discrepancy to resolve | d9_easyship/fixtures | UK to US mug quote returns duty 14.44 on 37.99 (28% base + 10% Section 301). Needs 8 to 10 digit code; with 6 digits it chose the 28% hotel/restaurant ware line. Our mockup assumed 7.45 |

| D9b | Easyship shipment creation, UK to US, DDP | 1 Nov 2026 | GREEN | d9_easyship/fixtures/shipment_create.json | Shipment ESGB369020643 created from Stoke-on-Trent to New York with incoterms DDP on FedEx International Connect Plus. Label not bought (would need paid billing); label purchase untested |

## D1 findings
- Order 1AE897264Y697121N: create, buyer approve, capture all worked. Capture status COMPLETED.
- Breakdown kept intact: item_total 38.00, shipping 14.00, tax_total 7.45, total 59.45 USD. Buyer receipt shows "Tax $7.45" as its own line with SKU KILN-MUG-01.
- Currency: UK seller received USD; PayPal converted to GBP itself (41.07 GBP at 0.7226). Confirms we do no FX.
- Fee: PayPal fee 2.62 USD was taken on the full 59.45, including the duty. The seller pays a processing fee on the duty they collect. Product decision needed: absorb it, or show it in pricing.
- Sandbox accounts must not be India-registered: Indian accounts cannot pay or receive USD ("seller doesn't accept payments in your currency"). Use UK business seller + US personal buyer.
- Receipt shows the business account name ("Test Store"), not brand_name. Rename the sandbox business account to "Kiln & Co." before recording the demo.
- Network: Claude's sandbox and the Cowork VM cannot reach api-m.sandbox.paypal.com (proxy 403). PayPal calls run from a team laptop unless the domain is allowlisted.

| D6 EU VAT (TEDB) | Green, 1 Nov | SOAP at https://ec.europa.eu/taxation_customs/tedb/ws/ needs SOAPAction and the types namespace; Greece is "EL"; 27 standard rates fetched (fixture d6_tedb/eu_vat_standard.json). Fallback not needed. |
| D7 Claude classifier | Green, 1 Nov | Haiku 5.5 only, thinking off, closed list of 38 HS6 codes, 2 independent calls. 30 listings: 96.7% exact 6-digit, calls agreed 100%, p95 1.96 s (bar 8 s), about $0.003 per product at an assumed $1/$5 per MTok (bar $0.02). One miss: vase 6913.90 vs 6914.90, flagged by the model with a question. Caveat: closed list is small; re-test on the full chapters in Sprint 1. Sonnet not needed. |
| D4 EU TARIC | Amber, 1 Nov | TARIC measures page and tullverket.se are reachable (HTTP 200) but duty measures are not parsed yet; fallback is a dated snapshot of our codes. |
| D11 Share images | Green, 1 Nov | Playwright headless Chromium: about 80 ms per 1200x630 PNG (bar 2 s). Real fonts and footnote layout to check in Sprint 1. |
| D12 Evaluation set | Amber, 1 Nov | 200 listings (40 types x 5) in d12_eval/listings.json, labels set by Claude and audited by a Haiku subagent against the USITC HTS: 35 of 40 types correct, 0 wrong, 5 ambiguous (vase, planter, tile, gloves, dress; flagged ask-expected). Haiku 5.5 scored 96.5% to 97.5% exact 6-digit, 99% agreement between calls; its misses are mostly these ambiguous types, where it asked a question. Needs a human spot-check of a handful and real marketplace listings before the accuracy claim is made public. Templated, so not independent of the label author. |
