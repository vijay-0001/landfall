"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, shareImageUrl } from "@/lib/api/client";
import type { Destination, TimeMachinePoint } from "@/lib/api/models";
import { useAsync } from "@/lib/hooks";
import { formatMoney, formatMoneyShort, toMinor } from "@/lib/money";
import { fmtDate, Logo, Skeleton } from "./ui";

interface Initial { product: string; origin: string; destination: Destination; date: string | null }

const ts = (iso: string) => Date.parse(`${iso}T00:00:00Z`);
const num = (m: { amount: string }) => toMinor(m.amount) / 100;
const monthYear = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });

export function TimeMachine({ initial }: { initial: Initial }) {
  const [product, setProduct] = useState(initial.product);
  const [origin, setOrigin] = useState(initial.origin);
  const [destination, setDestination] = useState<Destination>(initial.destination);
  const [idx, setIdx] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const opts = useAsync(() => api.getTimeMachineOptions(), "tm-options");
  const series = useAsync(() => api.getTimeMachineSeries(product, origin, destination), `${product}|${origin}|${destination}`);
  const s = series.data;
  const points = useMemo<TimeMachinePoint[]>(() => s?.points ?? [], [s]);

  const cur = useMemo(() => {
    if (!points.length) return 0;
    if (idx !== null && idx < points.length) return idx;
    const target = initial.date ?? s?.today ?? points[points.length - 1].date;
    let best = 0;
    for (let i = 0; i < points.length; i++) if (points[i].date <= target) best = i;
    return best;
  }, [idx, points, initial.date, s?.today]);

  const pickProduct = (v: string) => { setProduct(v); setIdx(null); };
  const pickOrigin = (v: string) => { setOrigin(v); setIdx(null); };
  const pickDest = (v: string) => { setDestination(v as Destination); setIdx(null); };

  const point = points[cur];
  const first = points[0];
  const cd = point?.buyer_total.currency ?? "USD";

  const data = useMemo(() => points.map((p) => {
    const past = !p.is_future;
    return { t: ts(p.date), total: num(p.buyer_total), past: past ? num(p.buyer_total) : null, future: p.is_future ? num(p.buyer_total) : null, date: p.date };
  }), [points]);
  // join the dashed segment to the solid line
  const lastPast = data.filter((d) => d.past !== null).at(-1);
  if (lastPast) { const nextFuture = data.find((d) => d.future !== null && d.t >= lastPast.t); if (nextFuture && lastPast.future === null) lastPast.future = lastPast.past; }
  const ticks = points.filter((p) => /-(01|04|07|10)-01$/.test(p.date)).map((p) => ts(p.date));
  const ys = data.map((d) => d.total);
  const lo = Math.floor((Math.min(...ys, 1e9) - 1) / 5) * 5;
  const hi = Math.ceil((Math.max(...ys, 0) + 1) / 5) * 5;

  const shareUrl = typeof window === "undefined" ? "" : `${window.location.origin}/time-machine?product=${product}&origin=${origin}&destination=${destination}${point ? `&date=${point.date}` : ""}`;
  async function share() {
    const text = `${s?.headline ?? "Tariff Time Machine"}`;
    try {
      if (navigator.share) { await navigator.share({ title: "Tariff Time Machine", text, url: shareUrl }); return; }
      await navigator.clipboard.writeText(shareUrl);
      setToast("Link copied. The share image is under the chart.");
    } catch { setToast("Copy the address bar link to share this view."); }
    setTimeout(() => setToast(null), 4000);
  }

  return (
    <div className="dark-page">
      <header className="dark-head">
        <Link className="brand" href="/"><Logo /> Landfall</Link>
        <span className="muted" style={{ marginLeft: "auto", fontSize: 13, color: "#9fb3d1" }}>Public page · no sign-up</span>
      </header>
      <main className="dark-body">
        <section style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 980 }}>
          <div style={{ fontSize: 13, letterSpacing: "0.1em", color: "#f3b48c" }}>TARIFF TIME MACHINE</div>
          <h1 style={{ fontSize: "clamp(30px, 5vw, 48px)", lineHeight: 1.08, color: "#fff" }}>
            {s ? s.headline : <Skeleton h={52} />}
          </h1>
        </section>

        <section aria-label="Choose" className="row" style={{ gap: 12, alignItems: "flex-end" }}>
          {([
            ["Product", product, pickProduct, opts.data?.products],
            ["From", origin, pickOrigin, opts.data?.origins],
            ["To", destination, pickDest, opts.data?.destinations],
          ] as const).map(([label, value, set, list]) => (
            <label key={label} style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, color: "#9fb3d1" }}>
              {label}
              <select value={value} onChange={(e) => set(e.target.value)} disabled={!list}>
                {(list ?? [{ id: value, label: value }]).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
            </label>
          ))}
        </section>

        <section aria-label="Price over time" className="dark-card">
          {series.error ? (
            <div className="errbox" role="alert">Could not load this series. <button type="button" className="btn btn-warn btn-sm" onClick={series.reload}>Try again</button></div>
          ) : !s || !point || !first ? (
            <div className="stack"><Skeleton h={50} w="40%" /><Skeleton h={300} /></div>
          ) : (
            <div className="fade-in" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div className="row" style={{ gap: 28, alignItems: "flex-end" }}>
                <div className="stack" style={{ gap: 2 }}>
                  <span style={{ fontSize: 13, color: "#9fb3d1" }}>{point.is_future ? `From ${fmtDate(point.date)} the buyer will pay` : `On ${fmtDate(point.date)} the buyer paid`}</span>
                  <span className="big-num" aria-live="polite">{formatMoney(point.buyer_total)}</span>
                </div>
                <div className="stack" style={{ gap: 2 }}>
                  <span style={{ fontSize: 13, color: "#9fb3d1" }}>In {monthYear(first.date)}</span>
                  <span style={{ fontFamily: "var(--font-head)", fontSize: 28, fontWeight: 700, color: "#c9d4e5" }}>{formatMoney(first.buyer_total)}</span>
                </div>
                <div className="stack" style={{ gap: 2 }}>
                  <span style={{ fontSize: 13, color: "#9fb3d1" }}>of which duty and tax</span>
                  <span style={{ fontFamily: "var(--font-head)", fontSize: 28, fontWeight: 700, color: "#7fd1c7" }}>{formatMoney(point.duty_and_tax)}</span>
                </div>
                {s.has_illustrative && <span className="pill" style={{ marginLeft: "auto", fontSize: 12, color: "#9fb3d1" }}>Some values are illustrative and labelled in the table</span>}
              </div>
              {point.label && <div style={{ color: "#f3b48c", fontWeight: 600 }}>{point.label}{point.source_ref ? <span style={{ color: "#9fb3d1", fontWeight: 400 }}> · {point.source_url ? <a href={point.source_url}>{point.source_ref}</a> : point.source_ref}</span> : null}</div>}

              <div role="img" aria-label={`Step chart of the buyer total from ${formatMoney(first.buyer_total)} in ${monthYear(first.date)} to ${formatMoney(points[points.length - 1].buyer_total)} at the end of the series. The table below lists every value.`} style={{ width: "100%", height: 320 }}>
                <ResponsiveContainer>
                  <LineChart data={data} margin={{ top: 12, right: 16, bottom: 4, left: 0 }}>
                    <CartesianGrid stroke="#2e406a" vertical={false} />
                    <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} ticks={ticks} stroke="#9fb3d1" tick={{ fill: "#9fb3d1", fontSize: 12 }}
                      tickFormatter={(v: number) => new Date(v).toLocaleDateString("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" })} />
                    <YAxis domain={[lo, hi]} ticks={Array.from({ length: Math.floor((hi - lo) / 5) + 1 }, (_, i) => lo + 5 * i)} stroke="#9fb3d1" width={54} tick={{ fill: "#9fb3d1", fontSize: 12 }} tickFormatter={(v: number) => formatMoneyShort({ amount: String(v), currency: cd })} />
                    <Tooltip cursor={{ stroke: "#fff", strokeWidth: 1 }} contentStyle={{ background: "#14213d", border: "1px solid #3b4d6e", borderRadius: 10, color: "#fff" }}
                      labelFormatter={(v) => fmtDate(new Date(Number(v)).toISOString())} formatter={(v) => [formatMoney({ amount: Number(v).toFixed(2), currency: cd }), "Buyer total"]} />
                    <Line type="stepAfter" dataKey="past" stroke="#7fd1c7" strokeWidth={4} dot={false} isAnimationActive={false} connectNulls />
                    <Line type="stepAfter" dataKey="future" stroke="#e07a3f" strokeWidth={4} strokeDasharray="8 8" dot={false} isAnimationActive={false} connectNulls />
                    {points.map((p, i) => p.is_change_date ? <ReferenceDot key={i} x={ts(p.date)} y={num(p.buyer_total)} r={6} fill="#e07a3f" stroke="none" ifOverflow="extendDomain" /> : null)}
                    <ReferenceLine x={ts(s.today)} stroke="#9fb3d1" strokeDasharray="2 4" label={{ value: "Today", fill: "#9fb3d1", fontSize: 12, position: "insideTopLeft" }} />
                    <ReferenceLine x={ts(point.date)} stroke="#fff" strokeWidth={2} />
                    <ReferenceDot x={ts(point.date)} y={num(point.buyer_total)} r={9} fill="#fff" stroke="none" ifOverflow="extendDomain" />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              <label style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 13, color: "#9fb3d1" }}>
                Drag through time ({fmtDate(first.date)} to {fmtDate(points[points.length - 1].date)})
                <input className="slider" type="range" min={0} max={points.length - 1} value={cur} onChange={(e) => setIdx(Number(e.target.value))}
                  aria-valuetext={`${fmtDate(point.date)}, ${formatMoney(point.buyer_total)}`} />
              </label>

              <details style={{ color: "#c9d4e5" }}>
                <summary style={{ cursor: "pointer", minHeight: 32 }}>View the same data as a table</summary>
                <div className="tablewrap" tabIndex={0} role="region" aria-label="Time Machine data table" style={{ maxHeight: 320, overflow: "auto", marginTop: 8 }}>
                  <table className="t" style={{ minWidth: 480, color: "#e7ecf5" }}>
                    <thead><tr><th>Date</th><th>Buyer total</th><th>Duty and tax</th><th>Note</th></tr></thead>
                    <tbody>{points.map((p, i) => (
                      <tr key={i} style={{ background: i === cur ? "#22325a" : undefined }}>
                        <td style={{ borderColor: "#2e406a" }}>{fmtDate(p.date)}</td><td style={{ borderColor: "#2e406a" }}>{formatMoney(p.buyer_total)}</td>
                        <td style={{ borderColor: "#2e406a" }}>{formatMoney(p.duty_and_tax)}</td>
                        <td style={{ borderColor: "#2e406a" }}>{[p.label, p.is_future ? "announced" : null, p.illustrative ? "illustrative" : null].filter(Boolean).join(" · ") || "–"}</td>
                      </tr>))}</tbody>
                  </table>
                </div>
              </details>
            </div>
          )}
        </section>

        <section className="row" style={{ gap: 14 }}>
          <button type="button" className="btn btn-orange" onClick={share}>Share this chart</button>
          <a className="btn btn-line" href={shareImageUrl({ product, origin, destination, date: point?.date })} download="landfall-time-machine.png">Download the image</a>
          <Link className="btn btn-line" href="/products">Sell abroad with duties included</Link>
          <span role="status" style={{ fontSize: 13, color: "#9fb3d1" }}>{toast ?? (s ? `Sources: ${s.sources.join(", ")}. Register ${s.register_version}.` : "")}</span>
        </section>
      </main>
    </div>
  );
}
