"use client";
import { useState } from "react";
import { ErrorBox, fmtDate, LoadingBlock } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Stamp } from "@/lib/api/models";
import { useAsync } from "@/lib/hooks";

const SHAPES = [
  { r: "50%", rot: -8, color: "#0A5C5B", border: "4px double #0E7C7B", w: 150, h: 150 },
  { r: "14px", rot: 6, color: "#8A2E0A", border: "4px solid #C2410C", w: 170, h: 120 },
  { r: "50%", rot: 4, color: "#1F3A5F", border: "4px double #1F3A5F", w: 150, h: 150 },
  { r: "14px", rot: -5, color: "#0A5C5B", border: "4px solid #0E7C7B", w: 170, h: 120 },
];

function StampView({ s, i }: { s: Stamp; i: number }) {
  const sh = SHAPES[i % SHAPES.length];
  return (
    <div className="stamp" role="img" aria-label={`Stamp: ${s.label}${s.earned_on ? `, earned ${fmtDate(s.earned_on)}` : ""}`}
      style={{ width: sh.w, height: sh.h, borderRadius: sh.r, border: sh.border, color: sh.color, transform: `rotate(${sh.rot}deg)`, animationDelay: `${i * 120}ms` }}>
      <span style={{ fontFamily: "var(--font-head)", fontWeight: 700, fontSize: s.label.length > 12 ? 14 : 17 }}>{s.label}</span>
      {s.note && <span style={{ fontSize: 11, fontWeight: 600 }}>{s.note}</span>}
      <span className="mono" style={{ fontSize: 12 }}>{fmtDate(s.earned_on).toUpperCase()}</span>
      {s.product_count > 0 && <span style={{ fontSize: 11, fontWeight: 600 }}>{s.product_count} {s.product_count === 1 ? "PRODUCT" : "PRODUCTS"}</span>}
    </div>
  );
}

export default function PassportPage() {
  const p = useAsync(() => api.getPassport(), "passport");
  const [msg, setMsg] = useState<string | null>(null);
  if (p.error) return <ErrorBox error={p.error} onRetry={p.reload} />;
  if (!p.data) return <LoadingBlock label="Loading passport" />;
  const d = p.data;
  const link = typeof window === "undefined" ? d.share_url : `${window.location.origin}${d.share_url}`;
  return (
    <>
      <div className="page-head">
        <div><h1>Your seller passport</h1><p>Every destination you ship to with duties included earns a stamp.</p></div>
        <div className="stack" style={{ alignItems: "flex-end", gap: 6 }}>
          <span className="kpi-label">Global Ready</span>
          <span style={{ fontFamily: "var(--font-head)", fontSize: 24, fontWeight: 700 }}>Level {d.level} · {d.level_name}</span>
          <div className="bar" style={{ width: 260 }} role="progressbar" aria-label={`Progress to level ${d.level + 1}`} aria-valuenow={d.next_level_progress_pct} aria-valuemin={0} aria-valuemax={100}><i style={{ width: `${d.next_level_progress_pct}%` }} /></div>
        </div>
      </div>
      <div className="row" style={{ alignItems: "flex-start", gap: 24 }}>
        <section aria-label="Passport pages" className="passport" style={{ flex: "3 1 520px", minWidth: 0 }}>
          <div className="ppage"><div className="cap">VISAS · DUTIES INCLUDED</div>
            <div className="row" style={{ gap: 18 }}>{d.stamps.length ? d.stamps.map((s, i) => <StampView key={s.destination} s={s} i={i} />) : <span className="muted">Your first duties-included order earns your first stamp.</span>}</div></div>
          <div className="ppage"><div className="cap">NEXT STAMPS</div>
            <div className="row" style={{ gap: 16 }}>{d.next_stamps.map((s) => (
              <div key={s.destination} style={{ width: 130, height: 130, borderRadius: "50%", border: "2px dashed #9a9483", color: "#5b5546", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center" }}>
                <b>{s.label}</b><span style={{ fontSize: 12 }}>{s.note}</span></div>))}</div>
            <p style={{ fontSize: 14, color: "#3d3a33" }}>Your own country needs no stamp.</p></div>
        </section>
        <aside aria-label="Share" className="stack" style={{ flex: "2 1 320px", minWidth: 0, gap: 16 }}>
          <section style={{ background: "var(--navy)", color: "#fff", borderRadius: 18, padding: 24, display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ fontSize: 12, letterSpacing: "0.1em", color: "#9fb3d1" }}>SHAREABLE BADGE</div>
            <div style={{ fontFamily: "var(--font-head)", fontSize: 28, fontWeight: 700, lineHeight: 1.15 }}>{d.badge_headline}</div>
            <div style={{ fontSize: 14, color: "#c9d4e5" }}>{d.badge_subline}</div>
            <div className="row">
              <a className="btn" style={{ background: "#fff", color: "var(--navy)" }} href={d.badge_image_url} download="landfall-badge.png">Download image</a>
              <button type="button" className="btn" style={{ background: "transparent", color: "#fff", borderColor: "#3b4d6e" }}
                onClick={async () => { try { await navigator.clipboard.writeText(link); setMsg("Link copied"); } catch { setMsg(link); } }}>Copy link</button>
            </div>
            <span role="status" className="fineprint" style={{ color: "#c9d4e5" }}>{msg}</span>
          </section>
          <section className="card stack"><h2 style={{ fontSize: 16 }}>How to reach Level {d.level + 1}</h2>
            {d.requirements.map((r) => <div key={r.text} className="row" style={{ flexWrap: "nowrap" }}><span aria-hidden="true" style={{ color: r.done ? "var(--teal)" : "#9a9483", fontWeight: 700 }}>{r.done ? "✓" : "○"}</span><span><span className="sr-only">{r.done ? "Done: " : "To do: "}</span>{r.text}</span></div>)}
            <p className="fineprint">Levels reward reviewing products and shipping duty-paid orders. They never depend on the amount of duty or on how you override.</p></section>
        </aside>
      </div>
    </>
  );
}
