"use client";
import { useState } from "react";
import { ErrorBox, fmtDate, LoadingBlock } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { QuotedField, RuleEditIn, RuleProposal, SourceHealth } from "@/lib/api/models";
import { useAsync } from "@/lib/hooks";
import { formatMoney } from "@/lib/money";

const FIELDS: [keyof RuleEditIn, string][] = [
  ["destination", "Destination"], ["code_pattern", "Codes covered"], ["origin_scope", "Origins"], ["measure", "Change"], ["rate", "Rate"], ["valid_from", "Effective from"], ["valid_to", "Effective to"],
];
const HEALTH: Record<SourceHealth["health"], { label: string; cls: string }> = {
  ok: { label: "Healthy", cls: "ok" }, stale_48h: { label: "Stale 48 h: checkout shows “rates last updated”", cls: "warn" }, paused_7d: { label: "Paused 7 days: duties-included off", cls: "warn" },
};

function RuleCard({ r, onAct }: { r: RuleProposal; onAct: (id: string, a: "approve" | "edit" | "reject", e?: RuleEditIn) => Promise<void> }) {
  const [edit, setEdit] = useState(false);
  const [draft, setDraft] = useState<RuleEditIn>({});
  const [busy, setBusy] = useState(false);
  const RATE_MEASURES = ["additional_duty", "base_duty", "total_rate_floor", "low_value_relief"];
  const required = (k: string) => k !== "valid_to" && (k !== "rate" || RATE_MEASURES.includes(r.measure.value ?? ""));
  const blank = FIELDS.filter(([k]) => required(k) && !(r[k as keyof RuleProposal] as QuotedField).value).map(([, l]) => l);
  const act = async (a: "approve" | "edit" | "reject", e?: RuleEditIn) => { setBusy(true); try { await onAct(r.id, a, e); setEdit(false); } finally { setBusy(false); } };
  return (
    <section className="grid grid-2" aria-label={`Notice review: ${r.notice_title}`} style={{ alignItems: "start" }}>
      <div className="card stack">
        <div className="fineprint">Source notice · {r.notice_doc_number} · {fmtDate(r.notice_published)}</div>
        <h2 style={{ fontSize: 18 }}>{r.notice_title}</h2>
        <blockquote style={{ margin: 0, fontSize: 14, lineHeight: 1.55, background: "#f7f8fa", borderRadius: 10, padding: 14 }}>“{r.notice_excerpt}”</blockquote>
        <a href={r.notice_url}>Open the full notice</a>
      </div>
      <div className="card stack" style={{ border: "2px solid var(--teal)" }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <b style={{ color: "var(--teal-dark)" }}>Rule proposed by the AI</b>
          <span className={`badge ${r.status === "pending" ? "info" : r.status === "rejected" ? "warn" : "ok"}`}>{r.status}</span>
        </div>
        <dl style={{ display: "grid", gridTemplateColumns: "130px 1fr", gap: "10px 14px", margin: 0, fontSize: 14 }}>
          {FIELDS.map(([k, label]) => {
            const f = r[k as keyof RuleProposal] as QuotedField;
            return (
              <div key={k} style={{ display: "contents" }}>
                <dt className="muted">{label}</dt>
                <dd style={{ margin: 0 }}>
                  {edit ? <input aria-label={label} defaultValue={f.value ?? ""} onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))} style={{ font: "inherit", minHeight: 36, width: "100%", borderRadius: 8, border: "1px solid var(--line-strong)", padding: "0 8px" }} />
                    : f.value ? <b className={k === "code_pattern" ? "mono" : ""}>{f.value}</b> : required(k) ? <span className="badge warn">Blank: needs ops</span> : <span className="badge info">None stated</span>}
                  {f.quote && !edit && <div className="fineprint">Source sentence: “{f.quote}”</div>}
                </dd>
              </div>
            );
          })}
          <dt className="muted">Sellers affected</dt><dd style={{ margin: 0 }}>{r.products_affected} products across {r.sellers_affected} sellers</dd>
        </dl>
        {blank.length > 0 && <div className="note-bar" role="status">The AI found no quoted sentence for: {blank.join(", ")}. Fill these before approving.</div>}
        {r.status === "pending" && (
          <div className="row">
            {edit ? <><button type="button" className="btn btn-primary" disabled={busy} onClick={() => act("edit", draft)}>Save edits and publish</button><button type="button" className="btn btn-ghost" onClick={() => setEdit(false)}>Cancel</button></>
              : <><button type="button" className="btn btn-primary" disabled={busy || blank.length > 0} onClick={() => act("approve")}>Approve and publish</button>
                <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setEdit(true)}>Edit rule</button>
                <button type="button" className="btn btn-warn" disabled={busy} onClick={() => act("reject")}>Reject</button></>}
          </div>
        )}
        <div className="fineprint">Approving adds a future-dated row and sends a Rule Radar alert to affected sellers. {r.model} · {r.prompt_version}</div>
      </div>
    </section>
  );
}

export default function Ops() {
  const sync = useAsync(() => api.getSync(), "ops-sync");
  const rules = useAsync(() => api.getRules(), "ops-rules");
  if (sync.error) return <div style={{ padding: 40 }}><ErrorBox error={sync.error} onRetry={sync.reload} /></div>;
  const act = async (id: string, a: "approve" | "edit" | "reject", e?: RuleEditIn) => { await api.ruleAction(id, a, e); rules.reload(); sync.reload(); };
  return (
    <div style={{ background: "#f3f4f7", minHeight: "100dvh" }}>
      <header style={{ background: "var(--navy)", color: "#fff", padding: "16px 40px", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <span style={{ fontFamily: "var(--font-head)", fontSize: 19, fontWeight: 700 }}>Landfall Ops</span>
        <span style={{ fontSize: 13, color: "#9fb3d1" }}>Internal · rate register</span>
        <span style={{ marginLeft: "auto", fontSize: 13, color: "#c9d4e5" }}>Register version {sync.data?.register_version ?? "…"}</span>
      </header>
      <main style={{ padding: "28px 40px", display: "flex", flexDirection: "column", gap: 22, maxWidth: 1240 }}>
        <section className="card stack" aria-label="Sync status">
          <h1 style={{ fontSize: 20 }}>Last night’s sync</h1>
          {!sync.data ? <LoadingBlock label="Loading sync" /> : (
            <div className="tablewrap" tabIndex={0} role="region" aria-label="Sync status table"><table className="t">
              <thead><tr><th>Source</th><th>Synced</th><th style={{ textAlign: "right" }}>Rows changed</th><th style={{ textAlign: "right" }}>Future-dated</th><th>Publish</th><th>Health</th></tr></thead>
              <tbody>{sync.data.sources.map((s) => (
                <tr key={s.id}><td><b>{s.name}</b></td><td>{s.last_success_at ? new Date(s.last_success_at).toLocaleString("en-GB", { hour: "2-digit", minute: "2-digit", day: "numeric", month: "short", timeZone: "UTC" }) + " UTC" : "never"}</td>
                  <td style={{ textAlign: "right" }}>{s.rows_changed}</td><td style={{ textAlign: "right" }}>{s.future_dated}</td>
                  <td><span className={`badge ${s.publish === "automatic" ? "ok" : "warn"}`}>{s.publish === "automatic" ? "Automatic" : "Needs review"}</span></td>
                  <td><span className={`badge ${HEALTH[s.health].cls}`}>{HEALTH[s.health].label}</span></td></tr>))}</tbody>
            </table></div>
          )}
          <div className="fineprint">A source with no sync for 48 hours shows “rates last updated” at checkout; after 7 days duties-included pauses for that destination.</div>
        </section>

        {sync.data && sync.data.shipment_cross_check.length > 0 && (
          <section className="card stack" aria-label="Shipment duty cross-check">
            <h2 style={{ fontSize: 18 }}>Shipment duty cross-check (Easyship quote vs Landfall)</h2>
            {sync.data.shipment_cross_check.map((c) => (
              <div key={c.order_id} className="row" style={{ gap: 18 }}>
                <span className="mono">{c.order_id}</span><span>Ours <b>{formatMoney(c.our_duty)}</b></span>
                <span>Easyship <b>{c.easyship_duty ? formatMoney(c.easyship_duty) : "–"}</b></span>
                <span>Difference <b>{c.difference ? formatMoney(c.difference) : "–"}</b></span><span className="fineprint">{c.note}</span>
              </div>))}
          </section>
        )}

        <h2 style={{ fontSize: 18 }}>Notices waiting for review</h2>
        {rules.error ? <ErrorBox error={rules.error} onRetry={rules.reload} /> : !rules.data ? <LoadingBlock label="Loading notices" /> : rules.data.length === 0 ? <div className="card empty">No notices waiting.</div> : rules.data.map((r) => <RuleCard key={r.id} r={r} onAct={act} />)}
      </main>
    </div>
  );
}
