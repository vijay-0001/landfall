// Server-rendered 1200x630 share card. The renderer service screenshots this page; no client JS, no network fonts.
import type { TimeMachineSeries } from "@/lib/api/models";
import { indexOnOrBefore, stepGeometry } from "@/lib/chart";
import { formatMoney } from "@/lib/money";

export const dynamic = "force-dynamic";
type SP = Promise<{ [k: string]: string | string[] | undefined }>;
const one = (v: string | string[] | undefined, d: string) => (Array.isArray(v) ? v[0] : v) ?? d;
const fmt = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

async function load(product: string, origin: string, destination: string): Promise<TimeMachineSeries | null> {
  const base = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
  const r = await fetch(`${base}/api/timemachine/series?product=${product}&origin=${origin}&destination=${destination}`, { cache: "no-store" });
  return r.ok ? ((await r.json()) as TimeMachineSeries) : null;
}

export default async function Share({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const s = await load(one(sp.product, "p_mug"), one(sp.origin, "GB"), one(sp.destination, "US"));
  const box: React.CSSProperties = { width: 1200, height: 630, background: "#14213D", color: "#E7ECF5", padding: "36px 48px", display: "flex", flexDirection: "column", gap: 14, fontFamily: "var(--font-body)", boxSizing: "border-box" };
  if (!s) return <div style={box}><h1 style={{ color: "#fff" }}>Tariff Time Machine</h1><p>No verified series for this view yet.</p></div>;
  const date = one(sp.date, s.today);
  const idx = indexOnOrBefore(s.points, date);
  const p = s.points[idx];
  const first = s.points[0];
  const g = stepGeometry(s.points, idx, 1104, 250);
  return (
    <div style={box} id="share-card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontFamily: "var(--font-head)", fontWeight: 700, fontSize: 22, color: "#fff" }}>Landfall · Tariff Time Machine</span>
        <span style={{ fontSize: 15, color: "#9FB3D1" }}>landfall demo</span>
      </div>
      <h1 style={{ fontSize: 38, lineHeight: 1.1, color: "#fff", margin: 0, maxWidth: 1050 }}>{s.headline}</h1>
      <div style={{ display: "flex", gap: 40, alignItems: "flex-end" }}>
        <div><div style={{ fontSize: 15, color: "#9FB3D1" }}>{p.is_future ? `From ${fmt(p.date)} the buyer will pay` : `On ${fmt(p.date)} the buyer paid`}</div>
          <div style={{ fontFamily: "var(--font-head)", fontSize: 64, fontWeight: 700, color: "#fff", lineHeight: 1 }}>{formatMoney(p.buyer_total)}</div></div>
        <div><div style={{ fontSize: 15, color: "#9FB3D1" }}>In {new Date(`${first.date}T00:00:00Z`).toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" })}</div>
          <div style={{ fontFamily: "var(--font-head)", fontSize: 34, fontWeight: 700, color: "#C9D4E5" }}>{formatMoney(first.buyer_total)}</div></div>
        <div><div style={{ fontSize: 15, color: "#9FB3D1" }}>of which duty and tax</div>
          <div style={{ fontFamily: "var(--font-head)", fontSize: 34, fontWeight: 700, color: "#7FD1C7" }}>{formatMoney(p.duty_and_tax)}</div></div>
      </div>
      <svg viewBox="0 0 1104 250" width={1104} height={250} role="img" aria-label="Buyer total over time">
        {g.yTicks.map((t, i) => <g key={i}><line x1={64} x2={1080} y1={t.y} y2={t.y} stroke="#2E406A" /><text x={0} y={t.y + 4} fill="#9FB3D1" fontSize={13}>{formatMoney({ amount: String(t.label), currency: p.buyer_total.currency }).replace(".00", "")}</text></g>)}
        {g.xTicks.map((t, i) => <text key={i} x={t.x} y={246} fill="#9FB3D1" fontSize={13}>{t.label}</text>)}
        <path d={g.past} fill="none" stroke="#7FD1C7" strokeWidth={4} />
        {g.future && <path d={g.future} fill="none" stroke="#E07A3F" strokeWidth={4} strokeDasharray="8 8" />}
        {g.dots.map((d, i) => <circle key={i} cx={d.x} cy={d.y} r={6} fill="#E07A3F" />)}
        <line x1={g.marker.x} x2={g.marker.x} y1={20} y2={214} stroke="#fff" strokeWidth={2} />
        <circle cx={g.marker.x} cy={g.marker.y} r={9} fill="#fff" />
      </svg>
      <div style={{ fontSize: 13, color: "#9FB3D1", marginTop: "auto" }}>
        Sources: {s.sources.join(", ")}. Register {s.register_version}. {s.has_illustrative ? "Some points are illustrative." : "Every point reads from the register with its source."} Numbers only; no commentary.
      </div>
    </div>
  );
}
