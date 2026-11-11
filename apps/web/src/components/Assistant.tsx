"use client";
import { useState } from "react";
import { api } from "@/lib/api/client";
import { useAsync } from "@/lib/hooks";

const IDEAS = ["Why this code?", "What would change it?", "Where can I check this?"];

/** A small box on the product page. It answers only from this product's listing, recommendation and links. It explains and points to sources;
 *  it cannot accept or override: the buttons below are the seller's. */
export function Assistant({ productId }: { productId: string }) {
  const chat = useAsync(() => api.getAssistant(productId), `assistant-${productId}`);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    setBusy(true); setErr(null);
    try { await api.askAssistant(productId, question); setQ(""); chat.reload(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <section className="card pad-lg stack" aria-label="Ask about this recommendation">
      <h2 style={{ fontSize: 18 }}>Ask about this recommendation</h2>
      <p className="fineprint">The assistant can explain the recommendation, say what would change it and point you to official sources. It cannot choose, accept or override for you: that stays with you.</p>
      <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0 }} aria-live="polite">
        {(chat.data ?? []).map((m) => (
          <li key={m.id} className="stack" style={{ gap: 4 }}>
            <div style={{ fontWeight: 600 }}>You: {m.question}</div>
            <div className={m.refused ? "note-bar" : ""} style={m.refused ? undefined : { background: "var(--teal-tint)", borderRadius: 10, padding: "8px 12px" }}>{m.refused && <b>I can’t do that. </b>}{m.answer}</div>
          </li>
        ))}
      </ul>
      <div className="row" style={{ gap: 8 }}>{IDEAS.map((i) => <button key={i} type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => send(i)}>{i}</button>)}</div>
      <form className="row" style={{ gap: 8, flexWrap: "nowrap" }} onSubmit={(e) => { e.preventDefault(); void send(q); }}>
        <label className="field" style={{ flex: 1 }}><span className="sr-only">Your question</span>
          <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={500} placeholder="Ask about this product’s code or origin" autoComplete="off" /></label>
        <button type="submit" className="btn btn-primary" disabled={busy || !q.trim()}>{busy ? "Thinking…" : "Ask"}</button>
      </form>
      {err && <div className="note-bar stop" role="alert">{err}</div>}
      {chat.error && <div className="note-bar" role="status">The earlier questions did not load.</div>}
    </section>
  );
}
