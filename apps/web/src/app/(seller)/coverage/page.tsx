"use client";
import { ErrorBox, LoadingBlock } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { CoverageSource } from "@/lib/api/models";
import { useAsync } from "@/lib/hooks";

const STATUS: Record<CoverageSource["status"], { label: string; cls: string }> = {
  ok: { label: "Up to date", cls: "ok" },
  stale: { label: "Over 48 hours", cls: "warn" },
  paused: { label: "Over 7 days", cls: "warn" },
  no_run_yet: { label: "No run yet", cls: "info" },
  manual: { label: "By hand", cls: "info" },
};

function when(iso: string | null): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";
}

export default function CoveragePage() {
  const c = useAsync(() => api.getCoverage(), "coverage");
  if (c.error) return <ErrorBox error={c.error} onRetry={c.reload} />;
  if (!c.data) return <LoadingBlock label="Loading coverage" />;
  const d = c.data;
  const notes = d.destinations.filter((x) => x.note);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Coverage and sources</h1>
          <p>Where Landfall prices import duty today, and where its rates come from. Register version <span className="mono">{d.register_version}</span>.</p>
        </div>
      </div>

      <section aria-labelledby="cov-matrix" className="card" style={{ marginBottom: 20 }}>
        <h2 id="cov-matrix">Covered today</h2>
        <p className="muted">A tick means Landfall prices duty for goods made in the country on the left when they are shipped to the country at the top.</p>
        <div className="tablewrap" tabIndex={0} role="region" aria-label="Covered countries">
          <table className="t" style={{ minWidth: 560 }}>
            <thead>
              <tr>
                <th scope="col">Goods made in</th>
                {d.destinations.map((x) => <th key={x.id} scope="col" style={{ textAlign: "center" }}>{x.name}{x.note ? <sup> *</sup> : null}</th>)}
              </tr>
            </thead>
            <tbody>
              {d.origins.map((o) => (
                <tr key={o.code} data-origin={o.code}>
                  <th scope="row" style={{ fontWeight: 600, textTransform: "none", letterSpacing: 0, fontSize: 14, color: "inherit", padding: "14px 8px", borderTop: "1px solid var(--line)" }}>{o.name}</th>
                  {d.destinations.map((x) => (
                    <td key={x.id} style={{ textAlign: "center" }}>
                      {o.destinations.includes(x.id) ? <span className="badge ok" role="img" aria-label={`${o.name} to ${x.name}: covered`}>✓</span> : null}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {notes.length > 0 && <p className="fineprint" style={{ marginTop: 10 }}>{d.destinations.map((x) => (x.note ? <span key={x.id}><sup>*</sup> {x.name}: {x.note} </span> : null))}</p>}
      </section>

      <section aria-labelledby="cov-src" className="card" style={{ marginBottom: 20 }}>
        <h2 id="cov-src">Where the rates come from</h2>
        <div className="tablewrap" tabIndex={0} role="region" aria-label="Rate sources">
          <table className="t" style={{ minWidth: 700 }}>
            <thead>
              <tr><th scope="col">Source</th><th scope="col">What it provides</th><th scope="col">Refreshed</th><th scope="col">Last good refresh</th><th scope="col">Status</th></tr>
            </thead>
            <tbody>
              {d.sources.map((s) => {
                const st = STATUS[s.status];
                return (
                  <tr key={s.id} data-source={s.id}>
                    <td style={{ fontWeight: 600 }}>{s.name}</td>
                    <td>{s.provides}</td>
                    <td>{s.refreshed}</td>
                    <td className="mono" style={{ fontSize: 13 }}>{when(s.last_success_at)}</td>
                    <td><span className={`badge ${st.cls}`}>{st.label}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="fineprint" style={{ marginTop: 10 }}>{d.stale_rule} {d.pause_rule}</p>
      </section>

      <section aria-label="Disclaimer" className="note-bar" role="note">{d.disclaimer}</section>
    </>
  );
}
