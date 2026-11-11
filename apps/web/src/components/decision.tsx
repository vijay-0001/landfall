"use client";
import { useRef, useState } from "react";
import type { DestinationPricing, Recommendation, TrailLine } from "@/lib/api/models";
import { formatMoney } from "@/lib/money";
import { api } from "@/lib/api/client";
import { useAsync } from "@/lib/hooks";
import { Amount, countryName, fmtDate } from "./ui";

/** Calculation trail in a modal dialog: every row used, its source and the arithmetic (NFR-03, FR-04). */
export function TrailButton({ pricing }: { pricing: DestinationPricing }) {
  const ref = useRef<HTMLDialogElement>(null);
  if (!pricing.trail.length) return null;
  return (
    <>
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => ref.current?.showModal()}>How this is calculated</button>
      <dialog ref={ref} className="drawer" aria-labelledby={`trail-${pricing.destination}`} onClick={(e) => { if (e.target === ref.current) ref.current?.close(); }}>
        <div className="in">
          <h3 id={`trail-${pricing.destination}`} style={{ fontSize: 20 }}>Calculation trail, {pricing.destination}</h3>
          <p className="fineprint">Rates as of {fmtDate(pricing.as_of)} · register {pricing.register_version}</p>
          {pricing.trail.map((l: TrailLine, i) => (
            <div key={i} className="card" style={{ padding: 12 }}>
              <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                <b>{l.label}</b><span className="mono">{formatMoney(l.base)} × {l.rate} = {formatMoney(l.amount)}</span>
              </div>
              <div className="fineprint">{l.source_url ? <a href={l.source_url}>{l.source_ref}</a> : l.source_ref}</div>
            </div>
          ))}
          <div className="row" style={{ justifyContent: "space-between" }}>
            <b>Total duty and tax</b><b><Amount m={pricing.duty_and_tax} /></b>
          </div>
          <button type="button" className="btn btn-primary" onClick={() => ref.current?.close()}>Close</button>
        </div>
      </dialog>
    </>
  );
}

/** What "Not included" means for a destination, and what the seller can do, in plain words. */
export function notIncludedHint(reason: string | null | undefined): string {
  const r = (reason ?? "").toLowerCase();
  if (r.includes("origin")) return "Landfall does not price goods from this origin yet (see Coverage and sources). If the origin shown is wrong, change it with Override; otherwise buyers here check out normally.";
  if (r.includes("low-value")) return "Above the order value the flat-duty route allows, so buyers here check out normally.";
  if (r.includes("exclusion")) return "A product exclusion may apply to this line, so Landfall will not guess the duty. Buyers here check out normally.";
  if (r.includes("ioss")) return "Needs an IOSS registration for the EU flat-duty route. Buyers here check out normally.";
  if (r.includes("paused") || r.includes("outside") || r.includes("not available")) return "Duties-included is switched off for this product, so buyers check out normally.";
  return "Landfall cannot price duty here yet, so buyers check out normally.";
}

export function DutyBreakdown({ pricing }: { pricing: DestinationPricing[] }) {
  const NAME = { US: "United States", EU: "European Union", GB: "United Kingdom", AU: "Australia", CA: "Canada" } as const;
  const notIncluded = pricing.filter((p) => p.paused_reason);
  return (
    <div className="tablewrap" tabIndex={0} role="region" aria-label="Duty and tax by destination">
      <table className="dest-table">
        <thead><tr><th>Destination</th><th>Rule applied</th><th>Duty and tax</th><th>Rates as of</th><th><span className="sr-only">Details</span></th></tr></thead>
        <tbody>
          {pricing.map((p) => (
            <tr key={p.destination}>
              <td><b>{NAME[p.destination]}</b></td>
              <td>{p.rule_applied}{p.paused_reason && <div className="fineprint">{notIncludedHint(p.paused_reason)}</div>}</td>
              <td>{p.paused_reason ? <span className="badge warn">Not included</span> : p.flat_label ? <span className="mono">{p.flat_label}</span> : p.duty_and_tax ? <b><Amount m={p.duty_and_tax} /></b> : <span className="muted">None</span>}</td>
              <td>{fmtDate(p.as_of)}</td>
              <td><TrailButton pricing={p} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {notIncluded.length > 0 && (
        <p className="fineprint" style={{ margin: "10px 4px 0" }}>
          <b>Not included</b> means Landfall will not add duty to the price for that destination. The buyer checks out as usual and customs or the carrier may bill them on delivery, the way it works without Landfall.
        </p>
      )}
    </div>
  );
}

export interface DecisionValue { action: "accepted" | "overridden"; code?: string; origin?: string; evidence_ref?: string }

/** Accept / Override with fine print directly underneath (FR-10 to FR-12). Evidence is optional and never blocks. */
export function AcceptOverrideBar({ rec, finePrint, version, disabledReason, refused = false, busy, onDecide }: {
  rec: Recommendation; finePrint: string; version: string; disabledReason?: string | null; refused?: boolean; busy: boolean; onDecide: (d: DecisionValue) => void;
}) {
  // refused: goods Landfall will not handle (legal, safety, moral): neither button. Otherwise a pause only means "no code found": Accept has nothing to accept, Override is the way forward.
  const noCode = rec.code === "none";
  const [overriding, setOverriding] = useState(false);
  const [code, setCode] = useState(noCode ? "" : rec.code);
  const [origin, setOrigin] = useState(rec.origin);
  const [evidence, setEvidence] = useState<string>("");
  const cov = useAsync(() => api.getCoverage().catch(() => null), "override-origins");  // the same list the Coverage page and the question's country list use
  const covered = (cov.data?.origins ?? []).map((o) => o.code);
  const origins = Array.from(new Set([...(rec.origin === "other" ? [] : [rec.origin]), ...covered])).sort((a, b) => countryName(a).localeCompare(countryName(b)));
  return (
    <div className="decide">
      {disabledReason && <div className="note-bar stop" role="status">{disabledReason}</div>}
      {noCode && !refused && <p className="fineprint">There is nothing to accept yet. Look the code up with the links above, then use Override to enter it.</p>}
      {overriding && (
        <div className="card stack fade-in" role="group" aria-label="Override the recommendation">
          {noCode && <p className="fineprint">Landfall could not find a code. Use the official links above to find the one you trust, type it here (8 or 10 digits, like 6912.00.44.00), and save. You remain the declarant.</p>}
          <label className="stack" style={{ gap: 4 }}>Customs code
            <input className="mono" placeholder="6912.00.44.00" value={code} onChange={(e) => setCode(e.target.value)} style={{ font: "inherit", minHeight: 44, borderRadius: 10, border: "1px solid var(--line-strong)", padding: "0 12px" }} inputMode="decimal" />
          </label>
          <label className="stack" style={{ gap: 4 }}>Country of origin
            <select value={origin} onChange={(e) => setOrigin(e.target.value)} style={{ font: "inherit", minHeight: 44, borderRadius: 10, border: "1px solid var(--line-strong)", padding: "0 12px", background: "#fff" }}>
              {origins.map((o) => <option key={o} value={o}>{countryName(o)}</option>)}
              <option value="other">A country Landfall does not price yet</option>
            </select>
            {origin === "other" && <small className="fineprint">Buyers check out as usual and Landfall adds no duty for this product.</small>}
          </label>
          <label className="stack" style={{ gap: 4 }}>Your evidence reference (optional)
            <input value={evidence} maxLength={200} placeholder="e.g. CBP ruling N123456, or supplier declaration 2026-114" onChange={(e) => setEvidence(e.target.value)}
              style={{ font: "inherit", minHeight: 44, borderRadius: 10, border: "1px solid var(--line-strong)", padding: "0 12px" }} />
            <small className="fineprint">Landfall keeps this note with your decision. It never asks you to upload anything.</small>
          </label>
          <div className="row">
            <button type="button" className="btn btn-primary" disabled={busy || !code.trim()} onClick={() => onDecide({ action: "overridden", code: code.trim(), origin, evidence_ref: evidence.trim() || undefined })}>Save override</button>
            <button type="button" className="btn btn-ghost" onClick={() => setOverriding(false)}>Cancel</button>
          </div>
        </div>
      )}
      {!overriding && (
        <div className="btns">
          <button type="button" className="btn btn-primary" disabled={busy || !!disabledReason} onClick={() => onDecide({ action: "accepted" })}>Accept</button>
          <button type="button" className="btn btn-ghost" disabled={busy || refused} onClick={() => setOverriding(true)}>Override</button>
        </div>
      )}
      <p className="fineprint" id="fine-print">{finePrint} <span className="mono">({version})</span></p>
    </div>
  );
}
