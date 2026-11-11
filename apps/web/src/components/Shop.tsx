"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { api } from "@/lib/api/client";
import type { ShopProduct, Storefront } from "@/lib/api/models";
import { MAX_QTY, useCart } from "@/lib/cart";
import { getKey } from "@/lib/merchant";
import { useAsync } from "@/lib/hooks";
import { addMoney, formatMoney, fromMinor, toMinor } from "@/lib/money";
import { countryName, ErrorBox, Skeleton } from "./ui";

export function ShipToSelect({ shop, value, onChange }: { shop: Storefront; value: string; onChange: (c: string) => void }) {
  return (
    <label className="row" style={{ gap: 8 }}>
      <span className="muted">Ship to</span>
      <select aria-label="Ship to country" value={value} onChange={(e) => onChange(e.target.value)} style={{ font: "inherit", minHeight: 44, borderRadius: 10, padding: "0 10px", border: "1px solid var(--line-strong)" }}>
        {shop.countries.map((c) => <option key={c.country} value={c.country}>{c.name} ({c.currency})</option>)}
      </select>
    </label>
  );
}

/** Landfall's hosted storefront is a preview, never a real shop: the strip says whose products these are, and that they are sample data when no store is connected. */
export function StoreHeader({ count, children }: { count?: number; children?: React.ReactNode }) {
  const info = useAsync(() => api.getShop().then((s) => s.shop).catch(() => null), "store-header");
  const own = useSyncExternalStore(() => () => undefined, () => !!getKey(), () => false);  // false while rendering on the server, then what this browser holds
  return (
    <>
      <div role="note" style={{ background: "var(--navy, #14213d)", color: "#fff", padding: "8px 40px", fontSize: 14 }}>
        {own ? <>Landfall&apos;s hosted storefront: a preview of what buyers see for your synced, accepted products. Your own checkout uses Landfall&apos;s widget instead. <Link href="/connect" style={{ color: "#7fd1c7" }}>Back to the console</Link></>
          : <>Sample shop: Landfall&apos;s built-in demo data, not a real store. <Link href="/connect" style={{ color: "#7fd1c7" }}>Connect your own store</Link></>}
      </div>
      <header style={{ borderBottom: "1px solid var(--line)", padding: "18px 40px", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", background: "#fff" }}>
        <Link href="/shop" style={{ fontFamily: "var(--font-head)", fontSize: 22, fontWeight: 700, color: "var(--ink)", textDecoration: "none" }}>{info.data?.name ?? "Shop"}</Link>
        {info.data && <span className="muted">{info.data.city}, {info.data.country}</span>}
        <span style={{ marginLeft: "auto" }} className="row">{children}{count !== undefined && <Link className="btn btn-ghost btn-sm" href="/shop#cart">Cart ({count})</Link>}</span>
      </header>
    </>
  );
}

function Tile({ p }: { p: ShopProduct }) {
  return <div role="img" aria-label={`${p.title} photo placeholder`} style={{ height: 120, borderRadius: 10, background: "var(--sand)", display: "grid", placeItems: "center", fontFamily: "var(--font-head)", fontSize: 34, color: "#5b5546" }}>{p.title.slice(0, 1)}</div>;
}

export function Shop() {
  const sp = useSearchParams();
  const shop = useAsync(() => api.getShop(), "shop");
  const cart = useCart();
  const [added, setAdded] = useState<string | null>(null);
  const paramShip = sp.get("ship");
  useEffect(() => { if (paramShip) cart.setShip(paramShip.toUpperCase()); }, [paramShip]); // eslint-disable-line react-hooks/exhaustive-deps
  const s = shop.data;
  const country = s?.countries.find((c) => c.country === cart.ship) ?? s?.countries[0];
  const cur = country?.currency;
  const byId = useMemo(() => new Map((s?.products ?? []).map((p) => [p.id, p])), [s]);
  const lines = cart.lines.filter((l) => byId.has(l.id));
  const count = lines.reduce((n, l) => n + l.qty, 0);
  const sellable = (p: ShopProduct) => !!cur && cur in p.prices;
  const subtotal = cur ? lines.reduce((m, l) => { const p = byId.get(l.id); const a = p?.prices[cur]; return a ? addMoney(m, fromMinor(toMinor(a) * l.qty, cur)) : m; }, fromMinor(0, cur)) : null;

  return (
    <div style={{ background: "var(--paper)", minHeight: "100dvh" }}>
      <StoreHeader count={count}>{s && <ShipToSelect shop={s} value={country?.country ?? "US"} onChange={cart.setShip} />}</StoreHeader>
      <main id="main" className="co-wrap">
        <section aria-label="Products" style={{ flex: "3 1 560px", minWidth: 0 }} className="stack">
          <h1 style={{ fontSize: 30 }}>The shop</h1>
          <p className="muted">Every price includes import duty and taxes for the country you pick, where the seller has accepted the customs recommendation. Nothing to pay at the door.</p>
          {shop.error ? <ErrorBox error={shop.error} onRetry={shop.reload} title="The shop did not load." /> : !s ? (
            <div className="grid grid-3">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} h={260} />)}</div>
          ) : s.products.length === 0 ? (
            <div className="empty">Nothing is for sale yet.</div>
          ) : (
            <ul className="grid grid-3" style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {s.products.map((p) => (
                <li key={p.id} className="card stack" data-testid={`product-${p.id}`} style={{ gap: 10 }}>
                  <Tile p={p} />
                  <div style={{ fontWeight: 700 }}>{p.title}</div>
                  <div className="fineprint" style={{ flex: 1 }}>{p.description}</div>
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <b>{cur && p.prices[cur] ? formatMoney({ amount: p.prices[cur], currency: cur }) : "–"}</b>
                    {p.origin && <span className="badge info">Made in {countryName(p.origin)}</span>}
                  </div>
                  {p.blocked
                    ? <span className="badge warn" style={{ alignSelf: "flex-start", whiteSpace: "normal" }}>Cannot be sold here</span>
                    : p.duties_included
                      ? <span className="badge ok" style={{ alignSelf: "flex-start" }}>Duties included</span>
                      : <span className="badge warn" style={{ alignSelf: "flex-start", whiteSpace: "normal" }} title={p.note ?? undefined}>Duties may be due on delivery</span>}
                  {p.blocked && p.note && <div className="fineprint">{p.note}</div>}
                  <button type="button" className="btn btn-primary btn-sm" disabled={!sellable(p) || p.blocked} onClick={() => { cart.add(p.id); setAdded(p.id); }}>
                    {p.blocked ? "Not available" : sellable(p) ? "Add to cart" : `Not sold in ${cur}`}
                  </button>
                  {added === p.id && <span role="status" className="fineprint">Added to your cart.</span>}
                </li>
              ))}
            </ul>
          )}
        </section>

        <aside id="cart" aria-label="Your cart" className="card pad-lg stack" style={{ flex: "1 1 320px", minWidth: 0, position: "sticky", top: 16 }}>
          <h2 style={{ fontSize: 20 }}>Your cart</h2>
          {!cart.ready ? <Skeleton h={60} /> : lines.length === 0 ? <p className="muted">Your cart is empty. Add something from the shop.</p> : (
            <>
              <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {lines.map((l) => {
                  const p = byId.get(l.id)!;
                  return (
                    <li key={l.id} className="stack" style={{ gap: 6, borderBottom: "1px solid var(--line)", paddingBottom: 10 }}>
                      <div style={{ fontWeight: 600 }}>{p.title}</div>
                      <div className="row" style={{ gap: 8 }}>
                        <button type="button" className="btn btn-ghost btn-sm" aria-label={`One fewer ${p.title}`} onClick={() => cart.setQty(l.id, l.qty - 1)}>−</button>
                        <span aria-live="polite" data-testid={`qty-${l.id}`}>{l.qty}</span>
                        <button type="button" className="btn btn-ghost btn-sm" aria-label={`One more ${p.title}`} disabled={l.qty >= MAX_QTY} onClick={() => cart.setQty(l.id, l.qty + 1)}>+</button>
                        <button type="button" className="btn btn-warn btn-sm" onClick={() => cart.remove(l.id)}>Remove</button>
                      </div>
                    </li>
                  );
                })}
              </ul>
              {subtotal && <div className="sum-row"><span>Items</span><b>{formatMoney(subtotal)}</b></div>}
              <p className="fineprint">Shipping and the exact duty are worked out at checkout for {country?.name}.</p>
              <Link className="btn btn-primary" href={`/checkout?ship=${country?.country ?? "US"}`}>Go to checkout</Link>
              <button type="button" className="btn btn-ghost btn-sm" onClick={cart.clear}>Empty the cart</button>
            </>
          )}
        </aside>
      </main>
    </div>
  );
}
