"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api/client";
import type { Destination, OrderReceipt, QuoteIn } from "@/lib/api/models";
import { parseItems, useCart } from "@/lib/cart";
import { useAsync } from "@/lib/hooks";
import { formatMoney } from "@/lib/money";
import { ShipToSelect, StoreHeader } from "./Shop";
import { Amount, ErrorBox, fmtDate, Logo, Skeleton } from "./ui";

export function Checkout() {
  const sp = useSearchParams();
  const cart = useCart();
  const shop = useAsync(() => api.getShop(), "shop");
  const orderId = sp.get("order_id");
  const cancelled = sp.get("cancelled") === "1";
  const fixed = parseItems(sp.get("items"));
  const items = fixed.length ? fixed : cart.lines;
  const shipCode = (sp.get("ship") ?? cart.ship).toUpperCase();
  const country = shop.data?.countries.find((c) => c.country === shipCode) ?? shop.data?.countries[0];
  const itemsKey = items.map((l) => `${l.id}:${l.qty}`).join(",");
  const quoteIn: QuoteIn | null = country && items.length
    ? { shop_id: "shop_kiln", destination: country.destination as Destination, currency: country.currency, ship_to_country: country.country, items: items.map((l) => ({ product_id: l.id, quantity: l.qty })) }
    : null;
  const quote = useAsync(() => (quoteIn ? api.postQuote(quoteIn) : Promise.resolve(null)), `quote-${country?.country}-${itemsKey}`);
  const [flipped, setFlipped] = useState(false);
  const [paying, setPaying] = useState(false);
  const [err, setErr] = useState<Error | null>(null);
  const [done, setDone] = useState<OrderReceipt | null>(null);
  const [capturing, setCapturing] = useState(Boolean(orderId));
  const [attempt, setAttempt] = useState(0);
  const cleared = useRef(false);
  const busy = paying || capturing;

  useEffect(() => {
    if (!orderId) return;
    let live = true;
    api.captureOrder(orderId).then(() => api.getOrder(orderId)).then(
      (r) => { if (live) { setDone(r); if (!cleared.current) { cleared.current = true; cart.clear(); } } },
      (e: Error) => { if (live) setErr(e); },
    ).finally(() => { if (live) setCapturing(false); });
    return () => { live = false; };
  }, [orderId, attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  async function pay() {
    if (!quoteIn) return;
    setPaying(true); setErr(null);
    try {
      const base = `${window.location.origin}/checkout?ship=${country?.country}`;
      const o = await api.createOrder({ quote: quoteIn, return_url: base, cancel_url: `${base}&cancelled=1` });
      window.location.href = o.approve_url;
    } catch (e) { setErr(e as Error); setPaying(false); }
  }

  const q = quote.data;
  const empty = cart.ready && !items.length && !orderId;
  const unpriced = useMemo(() => (q?.lines ?? []).filter((l) => !l.duties_included), [q]);
  return (
    <div style={{ background: "#fff", minHeight: "100dvh" }}>
      <StoreHeader>{shop.data && !orderId && <ShipToSelect shop={shop.data} value={country?.country ?? "US"} onChange={cart.setShip} />}</StoreHeader>
      <main id="main" className="co-wrap">
        <section aria-label="Order" style={{ flex: "3 1 520px", minWidth: 0, display: "flex", flexDirection: "column", gap: 20 }}>
          <h1 style={{ fontSize: 30 }}>{done ? "Receipt" : "Checkout"}</h1>
          {cancelled && !done && <div className="note-bar" role="status">You cancelled the payment at PayPal. Nothing was charged and your cart is still here.</div>}
          {capturing && !done && <div className="note-bar" role="status">Confirming your payment with PayPal…</div>}
          {orderId && err && !done && <ErrorBox error={err} title="We could not confirm the payment." onRetry={() => { setErr(null); setCapturing(true); setAttempt((a) => a + 1); }} />}
          {done ? (
            <div className="card pad-lg fade-in stack" role="status" style={{ borderColor: "var(--teal)", background: "#eff8f6" }}>
              <h2 style={{ fontSize: 22 }}>{done.duties_included ? "Order paid. Nothing to pay at the door." : "Order paid."}</h2>
              <p>Order <span className="mono">{done.order_id}</span> to {done.ship_to_label}. PayPal capture <span className="mono">{done.capture_id}</span> is <b>{done.status === "CAPTURED" ? "completed" : done.status.toLowerCase()}</b>.</p>
              <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {done.lines.map((l) => (
                  <li key={l.title} className="sum-row"><span>{l.quantity} × {l.title}{!l.duties_included && <span className="fineprint"> (duties may be due on delivery{l.unpriced_reason ? `: ${l.unpriced_reason}` : ""})</span>}</span><span>{formatMoney(l.unit_price)}</span></li>
                ))}
              </ul>
              <div className="sum-row"><span>Shipping</span><span>{formatMoney(done.shipping)}</span></div>
              {done.duties_included && <div className="sum-row"><span>Import duties and taxes, included</span><span>{formatMoney(done.tax_total)}</span></div>}
              <div className="sum-row" style={{ fontWeight: 700 }}><span>Total paid</span><span>{formatMoney(done.total)} {done.total.currency}</span></div>
              {done.duties_included && <p>Your PayPal receipt shows <Amount m={done.tax_total} /> as tax: that is the duty, already paid.</p>}
              <p className="fineprint">Rates locked at register {done.register_version}, for import on {fmtDate(done.rates_as_of)}.{done.shipment_id ? ` Shipment ${done.shipment_id} is booked delivered duty paid.` : ""}</p>
              <Link className="btn btn-ghost" href="/shop" style={{ alignSelf: "flex-start" }}>Back to the shop</Link>
            </div>
          ) : empty ? (
            <div className="card pad-lg stack"><b>Your cart is empty.</b><span className="muted">Pick something from the shop first.</span><Link className="btn btn-primary" href="/shop" style={{ alignSelf: "flex-start" }}>Go to the shop</Link></div>
          ) : (
            <>
              {(q?.lines ?? (quote.error ? [] : Array.from({ length: Math.max(1, items.length) }, () => null))).map((line, i) => (
                <div key={line?.product_id ?? i} className="card row" style={{ gap: 16, flexWrap: "nowrap" }}>
                  <div role="img" aria-label="Photo placeholder" style={{ width: 64, height: 64, borderRadius: 10, background: "var(--sand)", display: "grid", placeItems: "center", fontSize: 22, color: "#5b5546", flex: "none" }}>{line ? line.title.slice(0, 1) : ""}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {line ? <><div style={{ fontWeight: 600 }}>{line.title}</div><div className="muted">Qty {line.quantity}</div>
                      {!line.duties_included && <div className="fineprint">{line.unpriced_reason?.startsWith("Landfall will not price") ? `Duties may be due on delivery. ${line.unpriced_reason}` : `Duties may be due on delivery: ${(line.unpriced_reason ?? "not priced").replace(/\.$/, "").replace(/^./, (c) => c.toLowerCase())}`}</div>}</> : <Skeleton h={40} />}
                  </div>
                  {line && <b>{formatMoney({ amount: (Number(line.unit_price.amount) * line.quantity).toFixed(2), currency: line.unit_price.currency })}</b>}
                </div>
              ))}
              {q && q.duties_included && (
                <>
                  <div className={`flip${flipped ? " is-flipped" : ""}`}>
                    <div className="inner">
                      <div className="flipcard old" aria-hidden={flipped}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--orange-ink)", letterSpacing: "0.04em" }}>THE OLD WAY</div>
                        <div style={{ fontFamily: "var(--font-head)", fontSize: 22, fontWeight: 700 }}>Pay at the door</div>
                        <div style={{ fontSize: 14, color: "#3d3a33" }}>{q.old_way_note}</div>
                      </div>
                      <div className="flipcard new">
                        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--teal-dark)", letterSpacing: "0.04em" }}>WITH LANDFALL</div>
                        <div style={{ fontFamily: "var(--font-head)", fontSize: 22, fontWeight: 700 }}>{formatMoney({ amount: "0.00", currency: q.currency })} at the door</div>
                        <div style={{ fontSize: 14, color: "#1e3a38" }}>Duty is in the price{unpriced.length ? " for the items marked above" : ""}. Nothing more to pay on delivery.</div>
                      </div>
                    </div>
                  </div>
                  <button type="button" className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start", borderRadius: 999 }} aria-pressed={flipped} onClick={() => setFlipped((f) => !f)}>
                    {flipped ? "Show the old way" : "Flip to compare"}
                  </button>
                </>
              )}
              {q && !q.duties_included && <div className="note-bar stop" role="status">{q.paused_reason ?? "Duties may be due on delivery."}</div>}
              {quote.error && <ErrorBox error={quote.error} onRetry={quote.reload} title="We could not price this order." />}
            </>
          )}
        </section>

        {!done && !empty && (
          <aside aria-label="Summary" className="card pad-lg stack" style={{ flex: "2 1 340px", minWidth: 0, gap: 12 }}>
            <h2 style={{ fontSize: 18 }}>Order summary</h2>
            <div className="fineprint">Shipping to: {q?.ship_to_label ?? country?.name ?? "…"}</div>
            {quote.error ? null : !q ? <div className="stack"><Skeleton h={20} /><Skeleton h={20} /><Skeleton h={20} /><Skeleton h={30} /></div> : (
              <div className="fade-in stack" style={{ gap: 12 }}>
                {q.stale_note && <div className="note-bar" role="status">{q.stale_note}</div>}
                <div className="sum-row"><span>Items</span><span>{formatMoney(q.item_total)}</span></div>
                <div className="sum-row"><span>Shipping</span><span>{formatMoney(q.shipping)}</span></div>
                {q.duties_included
                  ? <div className="sum-row"><span>Import duties and taxes, included</span><span>{formatMoney(q.tax_total)}</span></div>
                  : <div className="sum-row muted"><span>Duties may be due on delivery</span><span>–</span></div>}
                {q.duties_included && Number(q.seller_discount.amount) > 0 && (
                  <div className="sum-row"><span>The seller covers part of the duty</span><span>−{formatMoney(q.seller_discount)}</span></div>)}
                {q.duties_included && <div className="fineprint">Estimated from the published rates in force on the expected import date, {fmtDate(q.rates_as_of)} (register {q.register_version}). Shown as tax on your PayPal receipt.</div>}
                <div style={{ height: 1, background: "var(--line)" }} />
                <div className="sum-row" style={{ fontSize: 20, fontWeight: 700 }}><span>Total</span><span data-testid="total">{formatMoney(q.total)} {q.currency}</span></div>
                {err && !orderId && <ErrorBox error={err} title="PayPal did not start." />}
                <button type="button" className="paypal-btn" disabled={busy} onClick={pay}>{busy ? "One moment…" : "Pay with PayPal"}</button>
                {q.duties_included && <div className="row fineprint" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}><Logo color="#0E7C7B" size={18} /><span>{q.delivered_duty_paid_note}</span></div>}
              </div>
            )}
          </aside>
        )}
      </main>
    </div>
  );
}
