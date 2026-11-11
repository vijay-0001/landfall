"use client";
import Link from "next/link";
import { use, useState } from "react";
import { AcceptOverrideBar, DutyBreakdown, type DecisionValue } from "@/components/decision";
import { Assistant } from "@/components/Assistant";
import { HelpPanel } from "@/components/Help";
import { BandBadge, ErrorBox, fmtDate, isNotCovered, LoadingBlock, originLabel, priceLine, statusOf } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useAsync } from "@/lib/hooks";

export default function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const d = useAsync(() => api.getProduct(id), `product-${id}`);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<Error | null>(null);
  const [asking, setAsking] = useState(false);
  const [changing, setChanging] = useState(false);
  async function ask() {
    setAsking(true); setErr(null);
    try { await api.recommend(id); d.reload(); } catch (e) { setErr(e as Error); } finally { setAsking(false); }
  }
  if (d.error) return <ErrorBox error={d.error} onRetry={d.reload} />;
  if (!d.data) return <LoadingBlock label="Loading product" />;
  const { product: p, recommendation: rec, fine_print: fine, fine_print_version: ver } = d.data;
  const st = statusOf(p);

  async function decide(v: DecisionValue) {
    if (!rec) return;
    setBusy(true); setErr(null);
    try {
      await api.decide(rec.id, { action: v.action, code: v.code ?? null, origin: v.origin ?? null, fine_print_version: ver, evidence_ref: v.evidence_ref ?? null });
      setChanging(false); d.reload();
    } catch (e) { setErr(e as Error); } finally { setBusy(false); }
  }

  return (
    <>
      <div className="fineprint"><Link href="/products">Products</Link> / {p.title}</div>
      <div className="page-head">
        <div><h1>{p.title}</h1>
          <p className="muted">Price {priceLine(p.prices)}</p></div>
        <span className={`badge ${st.cls}`}>{st.label}</span>
      </div>
      <section className="card pad-lg stack fade-in" aria-label="Listing">
        <div className="fineprint" style={{ textTransform: "uppercase", letterSpacing: "0.06em" }}>From the listing</div>
        <p>“{p.description}”</p>
        {(p.image_urls ?? []).length > 0 && (
          <div className="row" style={{ gap: 10, flexWrap: "wrap" }} aria-label="Product photos">
            {(p.image_urls ?? []).map((u, i) => (
              // eslint-disable-next-line @next/next/no-img-element -- the merchant's own photo address, shown as is
              <img key={u} src={u} alt={`${p.title}, photo ${i + 1} of ${(p.image_urls ?? []).length}`} referrerPolicy="no-referrer" loading="lazy" width={160} height={120}
                style={{ objectFit: "cover", borderRadius: 10, border: "1px solid var(--line)" }} />
            ))}
          </div>
        )}
      </section>

      {!rec ? (
        <section className="card pad-lg stack" aria-label="No recommendation yet">
          <b>No recommendation yet.</b>
          <p className="muted">Your product is saved. The AI has not produced a customs code and origin for it yet.</p>
          {err && <ErrorBox error={err} title="The AI could not answer." />}
          <div><button type="button" className="btn btn-primary" disabled={asking} onClick={ask}>{asking ? "Asking the AI…" : "Get the recommendation"}</button></div>
        </section>
      ) : (
        <>
          <section className="card pad-lg stack fade-in" aria-label="AI recommendation">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2 style={{ fontSize: 20 }}>AI recommendation</h2>
              <span className="fineprint">{rec.headline}</span>
            </div>
            <div className="grid grid-2">
              <div className="fact">
                <span className="kpi-label">Customs code (HS)</span>
                {isNotCovered(rec.code) ? (
                  <>
                    <span className="big" style={{ fontFamily: "var(--font-head)", fontSize: 24 }}>Outside what Landfall prices</span>
                    <span>Duties-included is not offered for this product, so buyers use standard checkout and may be billed at the door.</span>
                    <span className="fineprint"><b>Why:</b> {rec.code_reason}</span>
                  </>
                ) : (
                  <>
                    <span className="big">{rec.code}</span>
                    <span>{rec.code_description}</span>
                    <span className="fineprint"><b>Why:</b> {rec.code_reason}{rec.runner_up ? ` Next most likely: ${rec.runner_up}.` : ""}</span>
                    {rec.code_sources.length > 0 && <span className="fineprint">Sources: {rec.code_sources.map((s, i) => <span key={i}>{i ? ", " : ""}{s.url ? <a href={s.url}>{s.label}</a> : s.label}</span>)}</span>}
                    <BandBadge band={rec.band} />
                  </>
                )}
              </div>
              <div className="fact">
                <span className="kpi-label">Country of origin</span>
                <span className="big" style={{ fontFamily: "var(--font-head)", fontSize: 24 }}>{originLabel(rec.origin, p.origin_uncertain)}</span>
                <span className="fineprint"><b>Why:</b> {rec.origin_reason}</span>
                <ul className="fineprint" style={{ margin: 0, paddingLeft: 18 }}>
                  {rec.origin_signals.filter((s, i, all) => all.findIndex((x) => x.text === s.text && x.points_to === s.points_to) === i).map((s, i) => <li key={i}>{s.text}{s.points_to ? ` → ${originLabel(s.points_to)}` : ""}</li>)}
                </ul>
              </div>
            </div>
            {rec.questions.length > 0 && p.question_count > 0 && (
              <div className="note-bar" role="status">
                {p.question_count} quick {p.question_count === 1 ? "question changes" : "questions change"} what buyers pay.{" "}
                <Link href={`/products/${p.id}/questions`}>Answer {p.question_count === 1 ? "it" : "them"}</Link>. Until then the estimate uses the AI’s picks.
              </div>
            )}
          </section>

          <section className="card pad-lg stack fade-in" aria-label="What the buyer pays">
            <h2 style={{ fontSize: 18 }}>What the buyer pays on top of the price</h2>
            <DutyBreakdown pricing={rec.pricing} />
            <p className="fineprint">PayPal’s processing fee is charged on the full amount the buyer pays, including the duty, so you pay a fee on duty you collect. Sample figures follow the rate register on the date shown.</p>
          </section>

          {rec.help_prominent && <HelpPanel rec={rec} />}

          <section className="card pad-lg" aria-label="Decide">
            {p.review_status === "not_reviewed" || changing ? (
              <>
                {err && <ErrorBox error={err} title="That was not saved." />}
                {changing && <p className="fineprint">You are changing your earlier decision. The new one replaces it from now on; the old one stays in the audit trail.</p>}
                <AcceptOverrideBar key={rec.id} rec={rec} finePrint={fine} version={ver} busy={busy} disabledReason={changing ? null : p.paused_reason} refused={!!p.paused_reason?.startsWith("Landfall will not price this")} onDecide={decide} />
                {changing && <button type="button" className="btn btn-ghost" onClick={() => setChanging(false)}>Keep my earlier decision</button>}
              </>
            ) : (
              <div className="stack"><span className={`badge ${st.cls}`} style={{ alignSelf: "flex-start" }}>{st.label}</span>
                {rec.pricing.some((x) => x.supported && !x.paused_reason && x.destination !== "GB")
                  ? <p>Duties are included for buyers in {rec.pricing.filter((x) => x.supported && !x.paused_reason && x.destination !== "GB").map((x) => ({ US: "the United States", EU: "the European Union", GB: "the United Kingdom", AU: "Australia", CA: "Canada" } as const)[x.destination]).join(" and ")}. You stay responsible for the declaration, and you can review this again at any time. Rates as of {fmtDate(rec.pricing[0]?.as_of)}.</p>
                  : <p><b>No destination is priced for this product right now,</b> so buyers check out as usual and may be billed on delivery. Your decision is saved and takes effect for any destination Landfall can price later. You can review it at any time.</p>}
                <div className="row"><button type="button" className="btn btn-ghost" onClick={() => setChanging(true)}>Change my decision</button></div>
                <p className="fineprint">{fine} ({ver})</p></div>
            )}
          </section>

          {(rec.photo_reads ?? []).length > 0 && (
            <section className="card pad-lg stack fade-in" aria-label="What the AI read in your photos">
              <h2 style={{ fontSize: 18 }}>What the AI read in your photos</h2>
              <p className="fineprint">Read once, as text. The photos are not stored. This is evidence the AI weighed, not a decision: if a reading is wrong, change the recommendation with Override.</p>
              <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: 12 }}>
                {(rec.photo_reads ?? []).map((r, i) => (
                  <li key={r.url} className="row" style={{ gap: 14, alignItems: "flex-start", flexWrap: "nowrap" }}>
                    {/* eslint-disable-next-line @next/next/no-img-element -- the merchant's own photo address, shown as is */}
                    <img src={r.url} alt="" referrerPolicy="no-referrer" loading="lazy" width={96} height={72} style={{ objectFit: "cover", borderRadius: 8, border: "1px solid var(--line)", flex: "none" }} />
                    <div className="stack" style={{ gap: 2, minWidth: 0 }}>
                      <b>Photo {i + 1}</b>
                      {r.error ? <span className="fineprint">Could not be read: {r.error}.</span> : (
                        <>
                          <span>{r.label_text ? <>Label text: <b>“{r.label_text}”</b></> : "No label, tag or stamp text found on the product."}</span>
                          {r.made_in && <span>Made in: <b>{r.made_in}</b></span>}
                          {r.materials && <span className="fineprint">Looks like: {r.materials}</span>}
                          {r.notes && <span className="fineprint">{r.notes}</span>}
                        </>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {!rec.help_prominent && <HelpPanel rec={rec} />}

          <Assistant productId={p.id} />
        </>
      )}
    </>
  );
}
