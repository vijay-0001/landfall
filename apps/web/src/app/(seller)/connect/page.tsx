"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, keyIsKnown } from "@/lib/api/client";
import type { ImportOut, MerchantMe, SyncOut } from "@/lib/api/models";
import { priceLine } from "@/components/ui";
import { syncSentence } from "@/lib/syncText";
import { useAsync } from "@/lib/hooks";
import { KEY_SHAPE, clearKey, getKey, setDemo, setKey } from "@/lib/merchant";

const CURRENCIES = ["GBP", "USD", "EUR", "AUD"] as const;  // the currencies of the four destinations Landfall prices (US, UK, EU, Australia)
/** Countries a shop can ship from (a list, so no one has to know ISO codes). Greece is EL in the tariff data. */
const SHIP_FROM = ["GB", "US", "CA", "AU", "NZ", "IE", "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "EL", "HU", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
  "IN", "CN", "JP", "KR", "VN", "TH", "ID", "TR", "BD", "PK", "SG", "AE", "MX", "BR", "ZA"];
function shipFromName(c: string): string {
  if (c === "EL") return "Greece";
  try { return new Intl.DisplayNames(["en"], { type: "region" }).of(c) ?? c; } catch { return c; }
}
const SHIP_FROM_SORTED = [...SHIP_FROM].sort((a, b) => shipFromName(a).localeCompare(shipFromName(b)));

export default function ConnectPage() {
  return <Suspense fallback={null}><Connect /></Suspense>;
}

function Connect() {
  const needs = useSearchParams().get("needs") === "store";
  const [tick, setTick] = useState(0);
  const me = useAsync<MerchantMe | null>(() => (getKey() ? api.getMe().catch(() => null) : Promise.resolve(null)), `me-${tick}`);
  const connected = me.data;
  const refresh = () => setTick((t) => t + 1);

  return (
    <>
      {connected && <div className="fineprint"><Link href="/products">Products</Link> / Connect your store</div>}
      <div className="page-head"><div><h1>Connect your store</h1>
        <p>Landfall is for the shop you already have. Open an account, give Landfall your store&apos;s product feed, and the AI recommends a customs code and origin for each product. You accept or override. Your checkout then asks Landfall for the duty.</p></div></div>
      {!connected && needs && <div className="note-bar" role="status" style={{ maxWidth: 760, marginBottom: 14 }}>Landfall shows nothing until a store is connected. Open an account below, then connect your store&apos;s product feed.</div>}
      {connected ? <Connected me={connected} onChange={refresh} /> : <SignUp onDone={refresh} />}
    </>
  );
}

function SignUp({ onDone }: { onDone: () => void }) {
  const router = useRouter();
  const [f, setF] = useState({ name: "", country: "GB", city: "" });
  const [paste, setPaste] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((s) => ({ ...s, [k]: e.target.value }));

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true); setErr(null);
    try { const m = await api.createMerchant({ name: f.name.trim(), country: f.country.trim().toUpperCase(), city: f.city.trim() }); setKey(m.api_key); onDone(); }  // the keys live on their own page; nothing to read before importing products
    catch (e2) { setErr((e2 as Error).message); }
    setBusy(false);
  }
  async function usePasted(e: React.FormEvent) {
    e.preventDefault();
    const k = paste.trim();
    if (!KEY_SHAPE.test(k)) { setErr("That does not look like a Landfall API key (it starts with lf_test_ and is 56 characters)."); return; }
    setBusy(true); setErr(null);
    const known = await keyIsKnown(k);
    setBusy(false);
    if (known === false) { setErr("Landfall does not know that key. Check it was copied whole, or open a new account above."); return; }
    if (known === null) { setErr("Landfall did not answer, so the key could not be checked. Try again in a moment."); return; }
    setKey(k); onDone();
  }

  return (
    <div className="stack" style={{ gap: 20, maxWidth: 760 }}>
      <section className="card pad-lg stack" style={{ gap: 8 }} aria-label="How to connect a store">
        <h2 style={{ margin: 0 }}>How to connect your store</h2>
        <ol style={{ margin: 0, paddingLeft: 20, lineHeight: 1.6 }}>
          <li><b>Open an account</b> below. It takes a shop name, a country and a city.</li>
          <li><b>Paste your store&apos;s product feed address.</b> For the demo store, Kiln &amp; Co., it is on Kiln&apos;s <b>Shop admin</b> page (<span className="mono">/admin</span>, after staff login). A Shopify-style <span className="mono">/products.json</span> works.</li>
          <li><b>Add or change products in your own store.</b> Landfall syncs them every night, or press <b>Sync now</b> on the Products page.</li>
        </ol>
      </section>
      <form onSubmit={create} className="card pad-lg stack" style={{ gap: 16 }} aria-label="Open an account">
        <h2 style={{ margin: 0 }}>Open an account</h2>
        <label className="field"><span>Shop name</span><input value={f.name} onChange={set("name")} required minLength={2} maxLength={80} autoComplete="organization" /></label>
        <div className="row" style={{ gap: 12, alignItems: "flex-start" }}>
          <label className="field" style={{ flex: "1 1 160px" }}><span>Ships from</span>
            <select value={f.country} onChange={set("country")} required>{SHIP_FROM_SORTED.map((c) => <option key={c} value={c}>{shipFromName(c)}</option>)}</select></label>
          <label className="field" style={{ flex: "2 1 200px" }}><span>City</span><input value={f.city} onChange={set("city")} required minLength={2} maxLength={80} autoComplete="address-level2" /></label>
        </div>
        {err && <div className="note-bar stop" role="alert">{err}</div>}
        <div className="row"><button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Opening…" : "Open account"}</button></div>
      </form>
      <section id="demo" className="card pad-lg stack" style={{ gap: 8 }} aria-label="Built-in demo shop">
        <h2 style={{ margin: 0 }}>Just looking around?</h2>
        <p style={{ margin: 0 }}>The built-in demo shop has sample products and decisions so you can see every screen. It is not connected to any store.</p>
        <div className="row"><button type="button" className="btn btn-ghost" onClick={() => { setDemo(true); router.push("/products"); }}>Open the built-in demo shop</button></div>
      </section>
      <form onSubmit={usePasted} className="card pad-lg stack" style={{ gap: 12 }} aria-label="Use an existing key">
        <h2 style={{ margin: 0 }}>Already have a key?</h2>
        <p style={{ margin: 0 }} className="muted">Lost it? Landfall keeps only a fingerprint of your key, so it cannot show it again: open a new account above.</p>
        <label className="field"><span>API key</span><input value={paste} onChange={(e) => setPaste(e.target.value)} autoComplete="off" spellCheck={false} placeholder="lf_test_…" /></label>
        <div className="row"><button type="submit" className="btn btn-ghost" disabled={busy}>{busy ? "Checking…" : "Sign in with this key"}</button></div>
      </form>
    </div>
  );
}

function Connected({ me, onChange }: { me: MerchantMe; onChange: () => void }) {
  const [url, setUrl] = useState(me.feed_url ?? "");
  const [cur, setCur] = useState<(typeof CURRENCIES)[number]>("GBP");
  const [res, setRes] = useState<ImportOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [rec, setRec] = useState<{ done: number; total: number; failed: number } | null>(null);
  const [sync, setSync] = useState<SyncOut | null>(null);
  const [syncErr, setSyncErr] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  async function syncNow() {
    if (syncing) return;
    setSyncing(true); setSyncErr(null);
    try { setSync(await api.syncFeed()); onChange(); }
    catch (e2) { setSyncErr((e2 as Error).message); }
    setSyncing(false);
  }
  const lastSynced = (sync?.last_synced_at ?? me.last_synced_at) ? new Date((sync?.last_synced_at ?? me.last_synced_at) as string).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC" : null;

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true); setErr(null); setRes(null); setRec(null);
    try { setRes(await api.importFeed({ feed_url: url.trim(), currency: cur })); onChange(); }
    catch (e2) { setErr((e2 as Error).message); }
    setBusy(false);
  }
  async function recommendAll() {
    if (!res) return;
    const todo = res.created.filter((p) => p.review_status === "not_reviewed" && p.band === null);
    setRec({ done: 0, total: todo.length, failed: 0 });
    let done = 0, failed = 0;
    for (const p of todo) {
      try { await api.recommend(p.id); } catch { failed += 1; }
      done += 1;
      setRec({ done, total: todo.length, failed });
    }
  }
  const all = res ? [...res.created, ...res.updated] : [];

  return (
    <div className="stack" style={{ gap: 20, maxWidth: 860 }}>
      <div className="card pad-lg stack" style={{ gap: 8 }}>
        <h2 style={{ margin: 0 }}>{me.name}</h2>
        <p style={{ margin: 0 }}>{me.city}, {me.country} · {me.product_count} products</p>
        <p style={{ margin: 0 }} className="muted">Connecting your checkout to Landfall? Its two keys are on the <Link href="/keys">API keys</Link> page. Importing and syncing products needs no key.</p>
        <div className="row"><button type="button" className="btn btn-ghost" onClick={() => { clearKey(); setDemo(false); onChange(); }}>Sign out</button></div>
      </div>
      {res && (
        <div className="card pad-lg stack" style={{ gap: 14 }} aria-label="Import result">
          <h2 style={{ margin: 0 }}>Next: get the AI&apos;s recommendations</h2>
          <p style={{ margin: 0 }}>Imported {res.created.length} {res.created.length === 1 ? "product" : "products"}{res.updated.length ? `, updated ${res.updated.length}` : ""}{res.skipped.length ? `, skipped ${res.skipped.length} (see why below)` : ""}.</p>
          {res.skipped.length > 0 && (
            <ul style={{ margin: 0 }}>{res.skipped.map((s, i) => <li key={i}><b>{s.title}</b>: {s.reason}</li>)}</ul>
          )}
          {all.length > 0 && (
            <div className="tablewrap" tabIndex={0} role="region" aria-label="Imported products">
              <table className="t"><thead><tr><th>SKU</th><th>Product</th><th>Prices</th></tr></thead>
                <tbody>{all.map((p) => <tr key={p.id}><td className="mono">{p.sku}</td><td>{p.title}</td><td>{priceLine(p.prices)}</td></tr>)}</tbody></table>
            </div>
          )}
          <div className="row">
            <button type="button" className="btn btn-primary" onClick={recommendAll} disabled={!!rec && rec.done < rec.total}>
              {rec ? (rec.done < rec.total ? `Reading listing ${rec.done + 1} of ${rec.total}…` : "Run again") : "Get recommendations for all"}</button>
            <Link href="/products" className="btn btn-ghost">Go to my products</Link>
          </div>
          {rec && rec.done === rec.total && <div className="note-bar" role="status">{rec.total - rec.failed} recommendations ready{rec.failed ? `, ${rec.failed} could not be made (open the product to retry)` : ""}. Review each one on your products page: you accept or override.</div>}
          <small>The AI recommends. It never decides, and nothing is priced duty-paid until you accept.</small>
        </div>
      )}
      {me.feed_url && (
        <section className="card pad-lg stack" style={{ gap: 10 }} aria-label="Feed sync">
          <h2 style={{ margin: 0 }}>Keeping in sync</h2>
          <p style={{ margin: 0 }}>Landfall re-reads <span className="mono" style={{ overflowWrap: "anywhere" }}>{me.feed_url}</span> every night. <b id="last-synced">{lastSynced ? `Last synced ${lastSynced}.` : "Not synced yet."}</b></p>
          <div className="row"><button type="button" className="btn btn-primary" onClick={syncNow} disabled={syncing}>{syncing ? "Syncing…" : "Sync now"}</button></div>
          {syncErr && <div className="note-bar stop" role="alert">{syncErr}</div>}
          {sync && (
            <div className="note-bar" role="status" id="sync-result">
              {syncSentence(sync)}
            </div>
          )}
          <small>A changed title or description sends that product back to you to review; nothing is priced duty-paid on the old decision. A product that leaves your feed is no longer sold through the checkout.</small>
        </section>
      )}
      <form onSubmit={run} className="card pad-lg stack" style={{ gap: 14 }} aria-label="Import products">
        <h2 style={{ margin: 0 }}>Import your products</h2>
        <p style={{ margin: 0 }}>Paste your store&apos;s public product feed (a Shopify store serves one at <code className="mono">/products.json</code>). Landfall reads it, one product per SKU, and re-reads it every night. Nothing is changed in your store.</p>
        <label className="field"><span>Feed address</span><small>For the demo store, Kiln &amp; Co., it is shown in Kiln&apos;s Shop admin.</small><input type="url" value={url} onChange={(e) => setUrl(e.target.value)} required placeholder="https://your-store.com/products.json" /></label>
        <label className="field" style={{ maxWidth: 360 }}><span>Currency of the feed&apos;s prices</span><small>Only used when your feed lists one price per product. A feed with prices in several currencies brings its own.</small>
          <select value={cur} onChange={(e) => setCur(e.target.value as typeof cur)}>{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select></label>
        {err && <div className="note-bar stop" role="alert">{err}</div>}
        <div className="row"><button type="submit" className="btn btn-primary" disabled={busy || !url.trim()}>{busy ? "Reading your feed…" : "Import products"}</button></div>
      </form>
    </div>
  );
}
