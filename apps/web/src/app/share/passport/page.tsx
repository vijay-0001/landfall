// Server-rendered 1200x630 passport badge. The renderer screenshots this page; it is also the public link a seller shares.
import type { Metadata } from "next";
import type { Passport } from "@/lib/api/models";

export const dynamic = "force-dynamic";

async function load(shop?: string): Promise<Passport | null> {
  const base = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
  try {
    const r = await fetch(`${base}${shop ? `/api/passport/shared/${encodeURIComponent(shop)}` : "/api/passport"}`, { cache: "no-store" });
    return r.ok ? ((await r.json()) as Passport) : null;
  } catch {
    return null;
  }
}

type Search = Promise<{ shop?: string }>;

export async function generateMetadata({ searchParams }: { searchParams: Search }): Promise<Metadata> {
  const { shop } = await searchParams;
  const p = await load(shop);
  const title = p?.badge_headline ?? "Landfall seller passport";
  return { title, openGraph: { title, type: "website", images: [{ url: `/api/passport/badge.png${shop ? `?shop=${encodeURIComponent(shop)}` : ""}`, width: 1200, height: 630 }] } };
}

const fmt = (iso: string | null) => (iso ? new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).toUpperCase() : "");
const COLORS = ["#7FD1C7", "#F0A878", "#B8C7E3", "#7FD1C7"];

export default async function SharePassport({ searchParams }: { searchParams: Search }) {
  const { shop } = await searchParams;
  const p = await load(shop);
  const box: React.CSSProperties = { width: 1200, height: 630, background: "#14213D", color: "#E7ECF5", padding: "44px 56px", display: "flex", flexDirection: "column", gap: 20, fontFamily: "var(--font-body)", boxSizing: "border-box" };
  if (!p) return <div style={box} id="share-card"><h1 style={{ color: "#fff" }}>Landfall seller passport</h1><p>Passport not available right now.</p></div>;
  return (
    <div style={box} id="share-card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontFamily: "var(--font-head)", fontWeight: 700, fontSize: 24, color: "#fff" }}>Landfall · Seller passport</span>
        <span style={{ fontSize: 18, color: "#9FB3D1" }}>Level {p.level} · {p.level_name}</span>
      </div>
      <h1 style={{ fontFamily: "var(--font-head)", fontSize: 58, lineHeight: 1.08, color: "#fff", margin: 0, maxWidth: 1000 }}>{p.badge_headline}</h1>
      <p style={{ fontSize: 24, color: "#C9D4E5", margin: 0 }}>{p.badge_subline}</p>
      <div style={{ display: "flex", gap: 28, marginTop: "auto", alignItems: "center" }}>
        {p.stamps.map((s, i) => (
          <div key={s.destination} style={{ width: 150, height: 150, borderRadius: "50%", border: `4px double ${COLORS[i % COLORS.length]}`, color: COLORS[i % COLORS.length], transform: `rotate(${i % 2 ? 6 : -7}deg)`, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", gap: 4 }}>
            <span style={{ fontFamily: "var(--font-head)", fontWeight: 700, fontSize: s.label.length > 12 ? 14 : 17 }}>{s.label}</span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 13 }}>{fmt(s.earned_on)}</span>
          </div>
        ))}
        {p.stamps.length === 0 && <span style={{ fontSize: 22, color: "#9FB3D1" }}>The first duties-included order earns the first stamp.</span>}
      </div>
      <div style={{ fontSize: 14, color: "#9FB3D1" }}>Stamps are earned by real duties-included orders. Levels count products reviewed and duty-paid orders, never the amount of duty.</div>
    </div>
  );
}
