"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ErrorBox, Logo, Skeleton } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useAsync } from "@/lib/hooks";
import { setDemo } from "@/lib/merchant";

export default function Home() {
  const router = useRouter();
  const h = useAsync(() => api.getHowItWorks(), "how");
  const d = h.data;
  return (
    <main id="main" style={{ minHeight: "100dvh", padding: "clamp(20px, 4vw, 56px) clamp(16px, 4vw, 64px)", display: "flex", flexDirection: "column", gap: 36, maxWidth: 1440, margin: "0 auto" }}>
      <div className="stack" style={{ gap: 12 }}>
        <div className="row" style={{ gap: 10 }}><Logo color="#0E7C7B" size={30} /><span style={{ fontFamily: "var(--font-head)", fontSize: 22, fontWeight: 700 }}>Landfall</span></div>
        <h1 style={{ fontSize: "clamp(30px, 4.4vw, 44px)", maxWidth: 1100, letterSpacing: "-0.02em" }}>No surprise bills at the door. Duties included at PayPal checkout, for every seller.</h1>
        <p className="muted" style={{ fontSize: 18, maxWidth: 900 }}>The AI recommends the customs code, origin and duty. The seller accepts or overrides in one click. The buyer pays one clear price.</p>
        <div className="row" style={{ marginTop: 8 }}>
          <Link className="btn btn-primary" href="/connect">Connect your store</Link>
          <button type="button" className="btn btn-ghost" onClick={() => { setDemo(true); router.push("/products"); }}>Look around the demo shop</button>
          <Link className="btn btn-ghost" href="/time-machine">Try the Tariff Time Machine</Link>
          <Link className="btn btn-ghost" href="/shop">See a sample checkout</Link>
        </div>
      </div>

      {h.error ? <ErrorBox error={h.error} onRetry={h.reload} /> : (
        <ol className="fade-in" style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 16 }} aria-label="How it works">
          {(d?.steps ?? Array.from({ length: 5 }, () => null)).map((s, i) => (
            <li key={i} className="card stack" style={{ padding: 20, ...(i === 2 ? { border: "2px solid var(--teal)" } : {}) }}>
              {s ? <><div className="eyebrow">{s.n}</div><div style={{ fontWeight: 700, fontSize: 17 }}>{s.title}</div><div className="muted" style={{ fontSize: 14 }}>{s.body}</div></> : <><Skeleton h={14} w="40%" /><Skeleton h={20} /><Skeleton h={48} /></>}
            </li>
          ))}
        </ol>
      )}

      <section style={{ background: "var(--navy)", color: "#e7ecf5", borderRadius: 16, padding: 28, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 24, alignItems: "center" }} aria-label="Sources and what they power">
        <div className="stack">
          <div style={{ fontSize: 13, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "#9fb3d1" }}>Official sources, synced daily</div>
          <div className="row" style={{ gap: 8 }}>{(d?.sources ?? []).map((s) => <span key={s} className="pill">{s}</span>)}</div>
        </div>
        <div style={{ textAlign: "center", fontSize: 13, color: "#c9d4e5" }}>
          <svg width="64" height="24" viewBox="0 0 64 24" fill="none" stroke="#9FB3D1" strokeWidth="2" aria-hidden="true"><path d="M2 12h56" /><path d="M50 4l8 8-8 8" /></svg>
          <div>Effective-dated register: today’s rates and announced future ones</div>
        </div>
        <div className="stack">
          <div style={{ fontSize: 13, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "#9fb3d1" }}>Powers</div>
          <div className="row" style={{ gap: 8 }}>{(d?.powers ?? []).map((p, i) => <span key={p} style={{ background: i === 0 ? "var(--teal)" : "#f2e8df", color: i === 0 ? "#fff" : "var(--orange-ink)", borderRadius: 999, padding: "6px 12px", fontWeight: 600, fontSize: 14 }}>{p}</span>)}</div>
        </div>
      </section>

      <div className="row fineprint" style={{ gap: 24, marginTop: "auto" }}>
        {d && <><span><b style={{ color: "var(--ink)" }}>The AI is a helper.</b> {d.ai_note.replace("The AI is a helper. ", "")}</span><span><b style={{ color: "var(--ink)" }}>Hackathon scope:</b> {d.scope_note.replace("Hackathon scope: ", "")}</span></>}
      </div>
    </main>
  );
}
