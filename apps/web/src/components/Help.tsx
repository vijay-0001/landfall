"use client";
import type { Recommendation } from "@/lib/api/models";

/** Official places to look the customs code up, with the search words already filled in. Leads the page when Landfall found no code or is not sure. */
export function HelpPanel({ rec }: { rec: Recommendation }) {
  const links = rec.help_links ?? [];
  if (links.length === 0) return null;
  const body = (
    <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: 10 }}>
      {links.map((l) => (
        <li key={l.url} className="row" style={{ gap: 12, flexWrap: "nowrap", alignItems: "flex-start" }}>
          <a className="btn btn-ghost btn-sm" href={l.url} target="_blank" rel="noopener noreferrer" style={{ flex: "none" }}>{l.label}</a>
          <span className="fineprint">{l.hint}</span>
        </li>
      ))}
    </ul>
  );
  if (rec.help_prominent) {
    return (
      <section className="card pad-lg stack fade-in" aria-label="Help me find it" style={{ borderColor: "var(--orange-soft)", background: "var(--orange-tint)" }}>
        <h2 style={{ fontSize: 20 }}>Help me find it</h2>
        <p>Landfall is not sure of this one. These official sites are searched for <b>“{rec.help_terms}”</b> already. Find the code you trust, then use <b>Override</b> below to enter it. The decision stays yours.</p>
        {body}
      </section>
    );
  }
  return (
    <details className="card" aria-label="Check it yourself">
      <summary style={{ cursor: "pointer", fontWeight: 600 }}>Check it yourself: official sites, searched for “{rec.help_terms}”</summary>
      <div style={{ paddingTop: 12 }}>{body}</div>
    </details>
  );
}
