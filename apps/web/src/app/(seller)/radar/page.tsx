"use client";
import Link from "next/link";
import { useState } from "react";
import { Amount, Empty, ErrorBox, LoadingBlock } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { RadarAlert } from "@/lib/api/models";
import { useAsync } from "@/lib/hooks";

function Alert({ a, onChoice, nothingPriced }: { a: RadarAlert; onChoice: (id: string, c: "absorb" | "pass_on") => Promise<void>; nothingPriced: boolean }) {
  const [busy, setBusy] = useState(false);
  const act = a.status === "act";
  const pick = async (c: "absorb" | "pass_on") => { setBusy(true); try { await onChoice(a.id, c); } finally { setBusy(false); } };
  return (
    <article className="card pad-lg alert fade-in" aria-labelledby={`al-${a.id}`} style={act ? { borderColor: "#f0cdb8" } : undefined}>
      <div className="countdown" style={!act ? { background: "#eef1f7", color: "var(--navy-2)" } : undefined}>
        {a.status === "in_effect" ? <b style={{ fontSize: 22 }}>Live</b> : a.days_left !== null ? <><b>{a.days_left}</b>days</> : <b style={{ fontSize: 22 }}>Date TBC</b>}
      </div>
      <div className="stack" style={{ flex: 1, minWidth: 240 }}>
        <div className="fineprint" style={{ letterSpacing: "0.06em", color: "var(--orange-ink)", fontWeight: 600 }}>{a.effective_label}</div>
        <h2 id={`al-${a.id}`} style={{ fontSize: 20 }}>{a.title}</h2>
        <p>{a.summary}</p>
        {act && a.impact_per_order && (
          <>
            <div className="row">
              <button type="button" className={`btn ${a.choice === "absorb" ? "btn-primary" : "btn-ghost"}`} aria-pressed={a.choice === "absorb"} disabled={busy} onClick={() => pick("absorb")}>Absorb it: keep buyer price</button>
              <button type="button" className={`btn ${a.choice === "pass_on" ? "btn-primary" : "btn-ghost"}`} aria-pressed={a.choice === "pass_on"} disabled={busy} onClick={() => pick("pass_on")}>Pass it on{a.effective_from ? ` from ${new Date(a.effective_from).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" })}` : ""}</button>
              {a.source_url && <a href={a.source_url}>Read the notice</a>}
            </div>
            {a.scheduled_price_change && <div className="note-bar" role="status">Scheduled: {a.scheduled_price_change}. You can change this until the effective date.</div>}
            <span className="fineprint">Impact per order: <Amount m={a.impact_per_order} /></span>
          </>
        )}
        {!act && <div className="row"><span className="badge info">{a.status === "in_effect" ? (nothingPriced ? "In effect (nothing of yours is priced yet)" : "In today's prices") : a.status === "watching" ? "Watching" : a.affected_product_ids.length ? `${a.affected_product_ids.length} product${a.affected_product_ids.length === 1 ? "" : "s"}` : "All US orders"}</span>{a.source_url && <a href={a.source_url}>Source</a>}</div>}
      </div>
    </article>
  );
}

export default function Radar() {
  const r = useAsync(() => api.getRadar(), "radar");
  const cat = useAsync(() => api.getCatalogue().catch(() => null), "radar-catalogue");
  const nothingPriced = !!cat.data && cat.data.summary.ready_count === 0;
  if (r.error) return <ErrorBox error={r.error} onRetry={r.reload} />;
  if (!r.data) return <LoadingBlock label="Loading Rule Radar" />;
  const choose = async (id: string, c: "absorb" | "pass_on") => { await api.radarChoice(id, { choice: c }); r.reload(); };
  const now = r.data.filter((a) => a.status === "act");
  const later = r.data.filter((a) => a.status === "further_out" || a.status === "watching");
  const past = r.data.filter((a) => a.status === "in_effect");
  return (
    <>
      <div className="page-head"><div><h1>Rule Radar</h1><p>Announced rule changes that will reach your products, before they land.</p></div></div>
      {nothingPriced && <div className="note-bar" role="status">None of your products is priced duty-paid yet, so these changes do not alter any price you show. <Link href="/products">Accept your products</Link> and this page will show which ones each change affects.</div>}
      {now.length === 0 && later.length === 0 && past.length === 0 && <Empty title="Nothing on the radar">When an official rule is approved and affects your products, it shows up here with a countdown.</Empty>}
      {now.map((a) => <Alert key={a.id} a={a} onChoice={choose} nothingPriced={nothingPriced} />)}
      {later.length > 0 && <h2 style={{ fontSize: 18 }}>Further out</h2>}
      {later.map((a) => <Alert key={a.id} a={a} onChoice={choose} nothingPriced={nothingPriced} />)}
      {past.length > 0 && <h2 style={{ fontSize: 18 }}>Recently took effect</h2>}
      {past.map((a) => <Alert key={a.id} a={a} onChoice={choose} nothingPriced={nothingPriced} />)}
      <p className="fineprint">Only rules approved by Landfall ops or loaded automatically from official sources appear here. Every item links to its source.</p>
    </>
  );
}
