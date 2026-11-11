"use client";
import Link from "next/link";
import { use, useReducer, useRef, useState, useSyncExternalStore } from "react";
import { Amount, ErrorBox, LoadingBlock } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Question, Recommendation } from "@/lib/api/models";
import { useAsync } from "@/lib/hooks";
import { formatMoney } from "@/lib/money";
import { classifyDrag, currentQuestion, initSwipe, limitQuestions, primaryLabel, swipeReducer } from "@/lib/swipe";

function usePhone(): boolean | null {
  return useSyncExternalStore(
    (cb) => { const mq = window.matchMedia("(max-width: 860px)"); mq.addEventListener("change", cb); return () => mq.removeEventListener("change", cb); },
    () => window.matchMedia("(max-width: 860px)").matches,
    () => null,
  );
}

function usPricing(rec: Recommendation) { return rec.pricing.find((p) => p.destination === "US"); }

export default function Questions({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const detail = useAsync(() => api.getProduct(id), `q-${id}`);
  const phone = usePhone();
  const cov = useAsync(() => api.getCoverage().catch(() => null), "q-origins");  // the countries the "Somewhere else" list offers
  const [override, setRec] = useState<Recommendation | null>(null);
  const rec = override ?? detail.data?.recommendation ?? null;
  if (detail.error) return <ErrorBox error={detail.error} onRetry={detail.reload} />;
  if (!detail.data || !rec || phone === null) return <LoadingBlock label="Loading questions" />;
  const questions = limitQuestions(rec.questions);
  const title = detail.data.product.title;
  const origins = (cov.data?.origins ?? []).map((o) => ({ code: o.code, name: o.name }));
  if (questions.length === 0) {
    return <div className="card empty"><b>No questions for {title}.</b><div><Link href={`/products/${id}`}>Back to the recommendation</Link></div></div>;
  }
  const decided = detail.data.product.review_status !== "not_reviewed";
  return (
    <>
      {decided && <div className="note-bar" role="status" style={{ marginBottom: 12 }}>You have already {detail.data.product.review_status === "overridden" ? "overridden" : "accepted"} this product. A new answer only takes effect when you decide again: after answering, open the product and choose <b>Change my decision</b>.</div>}
      {phone
        ? <Cards rec={rec} setRec={setRec} questions={questions} title={title} id={id} origins={origins} />
        : <Form rec={rec} setRec={setRec} questions={questions} title={title} id={id} origins={origins} />}
    </>
  );
}

interface Props { rec: Recommendation; setRec: (r: Recommendation) => void; questions: Question[]; title: string; id: string; origins: { code: string; name: string }[] }

/** "Somewhere else" used to be a dead end. It is now a country list: any country Landfall prices, or (last) one it does not price yet. */
function OriginPicker({ q, origins, answer, onPick, current }: { q: Question; origins: { code: string; name: string }[]; answer: (qid: string, oid: string) => Promise<void>; onPick: (oid: string) => void; current?: string }) {
  if (q.id !== "q_origin") return null;
  const listed = new Set(q.options.map((o) => o.id));
  const more = origins.filter((o) => !listed.has(`origin_${o.code}`));
  return (
    <label className="field">
      <span>Somewhere else?</span>
      <select value={current && !listed.has(current) ? current : ""} aria-label="Another country of origin"
        onChange={(e) => { const v = e.target.value; if (v) void answer(q.id, v).then(() => onPick(v)); }}>  {/* selected once the answer is in: the named country joins the question's options only then */}
        <option value="">Choose another country…</option>
        {more.map((o) => <option key={o.code} value={`origin_${o.code}`}>{o.name}</option>)}
        <option value="origin_other">A country Landfall does not price yet</option>
      </select>
      <small>If you choose a country Landfall does not price yet, buyers check out as usual and Landfall adds no duty.</small>
    </label>
  );
}
/** The code questions offer the tariff's own wording, which reads oddly to a seller: say what it is and what to do when unsure. */
function TariffHint({ q }: { q: Question }) {
  if (q.id !== "q_code" && q.id !== "q_line") return null;
  return <p className="fineprint" style={{ margin: 0 }}>These are the customs tariff&apos;s own words, each with what a US buyer would pay. Choose the closest. Not sure? Keep the AI&apos;s pick: on the next page you can check the official sites or override.</p>;
}
const shown = (q: Question) => q.options.filter((o) => !(q.id === "q_origin" && o.id === "origin_other"));

function useAnswer(rec: Recommendation, setRec: (r: Recommendation) => void) {
  const [err, setErr] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  async function answer(qid: string, oid: string) {
    setBusy(true); setErr(null);
    try { const r = await api.answer(rec.id, { question_id: qid, option_id: oid }); setRec(r.recommendation); } catch (e) { setErr(e as Error); } finally { setBusy(false); }
  }
  return { answer, err, busy };
}

function Live({ rec }: { rec: Recommendation }) {
  const us = usPricing(rec);
  return <div className="note-bar" role="status" aria-live="polite">US buyer duty and tax at today’s rates: <b>{us?.duty_and_tax ? <Amount m={us.duty_and_tax} /> : "–"}</b></div>;
}

/** Desktop: the same questions as a plain form (EF-04). */
function Form({ rec, setRec, questions, title, id, origins }: Props) {
  const { answer, err } = useAnswer(rec, setRec);
  const [picked, setPicked] = useState<Record<string, string>>({});
  return (
    <>
      <div className="fineprint"><Link href="/products">Products</Link> / <Link href={`/products/${id}`}>{title}</Link> / Questions</div>
      <div className="page-head"><div><h1>{questions.length === 1 ? "One quick check" : `${questions.length} quick checks`}</h1><p>{title}: the answers below change what US buyers pay. Each option shows the difference.</p></div></div>
      {err && <ErrorBox error={err} />}
      <Live rec={rec} />
      {questions.map((q, n) => (
        <fieldset key={q.id} className="card pad-lg stack" style={{ border: "1px solid var(--line)" }}>
          <legend className="eyebrow" style={{ padding: "0 6px" }}>Question {n + 1} of {questions.length}</legend>
          <h2 style={{ fontSize: 20 }}>{q.text}</h2>
          {q.help && <p className="muted">{q.help}</p>}
          <div className="stack" role="radiogroup" aria-label={q.text}>
            {shown(q).map((o) => {
              const on = (picked[q.id] ?? q.options.find((x) => x.is_ai_pick)?.id) === o.id;
              return (
                <button key={o.id} type="button" role="radio" aria-checked={on} className="opt" onClick={() => { setPicked((p) => ({ ...p, [q.id]: o.id })); void answer(q.id, o.id); }}>
                  <span>{o.label}{o.is_ai_pick ? <span className="badge info" style={{ marginLeft: 8 }}>AI’s pick</span> : null}</span>
                  <span className="mono muted">{o.price_impact ? formatMoney(o.price_impact, { signed: true }) : "choose"}</span>
                </button>
              );
            })}
          </div>
          <TariffHint q={q} />
          <OriginPicker q={q} origins={origins} answer={answer} onPick={(oid) => setPicked((p) => ({ ...p, [q.id]: oid }))} current={picked[q.id]} />
        </fieldset>
      ))}
      <div className="row"><Link className="btn btn-primary" href={`/products/${id}`}>Continue to Accept or Override</Link></div>
    </>
  );
}

/** Phone: one card at a time with real swipe (right keeps the pick, left goes back) plus buttons. */
function Cards({ rec, setRec, questions, title, id, origins }: Props) {
  const { answer, err } = useAnswer(rec, setRec);
  const [state, dispatch] = useReducer((s: ReturnType<typeof initSwipe>, a: Parameters<typeof swipeReducer>[1]) => swipeReducer(s, a, questions), questions, initSwipe);
  const q = currentQuestion(state, questions);
  const start = useRef<{ x: number; y: number; t: number } | null>(null);
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  if (state.done || !q) {
    return (
      <div className="swipe-phone fade-in">
        <h1 style={{ fontSize: 26 }}>All set</h1>
        <Live rec={rec} />
        <p className="muted">Your answers are saved. Review the recommendation and accept or override.</p>
        <button type="button" className="btn btn-ghost" onClick={() => dispatch({ type: "back" })}>Back</button>
        <Link className="btn btn-primary" href={`/products/${id}`}>Continue to Accept or Override</Link>
      </div>
    );
  }
  const sel = state.selected[q.id];
  const next = () => { void answer(q.id, sel); dispatch({ type: "next" }); setDx(0); };
  return (
    <div className="swipe-phone">
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
        <Link href={`/products/${id}`} style={{ fontFamily: "var(--font-head)", fontWeight: 700, textDecoration: "none", color: "var(--ink)" }}>Landfall</Link>
        <span className="muted" style={{ fontSize: 13 }}>Question {state.index + 1} of {state.total}</span>
      </div>
      <div className="progress" aria-hidden="true">{questions.map((x, i) => <i key={x.id} className={i <= state.index ? "on" : ""} />)}</div>
      <div className="muted">{title} · one quick check before buyers see a price</div>
      {err && <ErrorBox error={err} />}
      <div style={{ position: "relative", flex: 1 }}>
        <div aria-hidden="true" style={{ position: "absolute", left: 14, right: 14, top: 14, bottom: -10, background: "#ece8de", borderRadius: 22 }} />
        <section aria-label="Question card" className="qcard" style={{ transform: `translateX(${dx}px) rotate(${dx / 30 - 1.5}deg)`, transition: dragging ? "none" : undefined }}
          onPointerDown={(e) => { setDragging(true); start.current = { x: e.clientX, y: e.clientY, t: e.timeStamp }; (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); }}
          onPointerMove={(e) => { if (start.current) { const d = e.clientX - start.current.x; if (Math.abs(d) > 6) setDx(d); } }}
          onPointerUp={(e) => {
            setDragging(false); const s0 = start.current; start.current = null; if (!s0) return;
            const intent = classifyDrag(e.clientX - s0.x, e.clientY - s0.y, e.timeStamp - s0.t, state.index > 0);
            setDx(0);
            if (intent === "keep") next(); else if (intent === "back") dispatch({ type: "back" });
          }}
          onPointerCancel={() => { start.current = null; setDragging(false); setDx(0); }}>
          {q.evidence_crop_label && <div role="img" aria-label={q.evidence_crop_label} style={{ height: 150, borderRadius: 14, background: "var(--sand)", display: "grid", placeItems: "center", fontSize: 13, color: "#5b5546", textAlign: "center", padding: 8 }}>[{q.evidence_crop_label}]</div>}
          <h1 style={{ fontSize: 22, lineHeight: 1.25 }}>{q.text}</h1>
          {q.help && <div className="muted" style={{ fontSize: 13 }}>{q.help}</div>}
          <div className="stack" role="radiogroup" aria-label={q.text} style={{ gap: 8 }}>
            {shown(q).map((o) => (
              <button key={o.id} type="button" role="radio" aria-checked={sel === o.id} className="opt" onClick={() => { dispatch({ type: "select", questionId: q.id, optionId: o.id }); void answer(q.id, o.id); }}>
                <span>{o.label}</span><span className="mono" style={{ fontSize: 13, textAlign: "right" }}>{o.price_impact ? `${sel === o.id ? "US buyer pays " : ""}${formatMoney(o.price_impact, { signed: true })}` : "choose"}</span>
              </button>
            ))}
          </div>
          <TariffHint q={q} />
          <OriginPicker q={q} origins={origins} answer={answer} onPick={(oid) => dispatch({ type: "select", questionId: q.id, optionId: oid })} current={sel} />
        </section>
      </div>
      <Live rec={rec} />
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <button type="button" className="btn btn-ghost" style={{ flex: 1 }} disabled={state.index === 0} onClick={() => dispatch({ type: "back" })}>Back</button>
        <button type="button" className="btn btn-primary" style={{ flex: 2 }} onClick={next}>{primaryLabel(q, sel)}</button>
      </div>
      <div className="fineprint" style={{ textAlign: "center" }}>Swipe right to keep the AI’s pick · left to go back</div>
    </div>
  );
}
