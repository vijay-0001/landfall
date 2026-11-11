"use client";
import Link from "next/link";
import { createColumnHelper, flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, useReactTable, type SortingState } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { Empty, ErrorBox, LoadingBlock, originLabel, statusOf } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Product } from "@/lib/api/models";
import { SyncBar } from "@/components/SyncBar";
import { bulkBlockReason, eligibleIds, sanitizeSelection } from "@/lib/bulk";
import { useAsync } from "@/lib/hooks";

const col = createColumnHelper<Product>();
const FILTERS = [["all", "All"], ["not_reviewed", "Not yet reviewed"], ["accepted", "Accepted"]] as const;

export default function Catalogue() {
  const cat = useAsync(() => api.getCatalogue(), "catalogue");
  const [filter, setFilter] = useState<(typeof FILTERS)[number][0]>("all");
  const [selected, setSelected] = useState<string[]>([]);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [recRun, setRecRun] = useState<{ done: number; total: number } | null>(null);
  const products = useMemo(() => cat.data?.products ?? [], [cat.data]);
  const rows = useMemo(() => products.filter((p) => filter === "all" || (filter === "accepted" ? p.review_status !== "not_reviewed" : p.review_status === "not_reviewed")), [products, filter]);

  const columns = useMemo(() => [
    col.display({
      id: "select", header: () => {
        const ids = eligibleIds(rows); const all = ids.length > 0 && ids.every((i) => selected.includes(i));
        return <input type="checkbox" aria-label="Select all High-confidence products" checked={all} disabled={ids.length === 0}
          onChange={() => setSelected(all ? [] : ids)} style={{ width: 20, height: 20 }} />;
      },
      cell: ({ row }) => {
        const p = row.original; const reason = bulkBlockReason(p);
        return <input type="checkbox" aria-label={reason ? `${p.title}: ${reason}` : `Select ${p.title}`} title={reason ?? undefined} disabled={!!reason}
          checked={selected.includes(p.id)} onChange={(e) => setSelected((s) => (e.target.checked ? [...s, p.id] : s.filter((x) => x !== p.id)))} style={{ width: 20, height: 20 }} />;
      },
    }),
    col.accessor("title", { header: "Product", cell: (c) => <b>{c.getValue()}</b> }),
    col.accessor("code", { header: "Code", cell: (c) => <span className="mono">{c.getValue() === "none" ? "Not covered" : (c.getValue() ?? "–")}</span> }),
    col.accessor((p) => originLabel(p.origin, p.origin_uncertain), { id: "origin", header: "Origin" }),
    col.accessor("ai_note", { header: "AI note", enableSorting: false, cell: (c) => <span className={rows[c.row.index]?.origin_uncertain ? "" : "muted"} style={rows[c.row.index]?.origin_uncertain ? { color: "var(--orange-ink)" } : undefined}>{c.getValue()}</span> }),
    col.accessor((p) => statusOf(p).label, { id: "status", header: "Status", cell: (c) => <span className={`badge ${statusOf(c.row.original).cls}`}>{c.getValue()}</span> }),
    col.display({ id: "action", header: () => <span className="sr-only">Action</span>, cell: ({ row }) => {
      const p = row.original;
      if (p.question_count > 0 && p.review_status === "not_reviewed") return <Link href={`/products/${p.id}/questions`}>Answer</Link>;
      if (p.review_status === "not_reviewed") return <Link className="btn btn-primary btn-sm" href={`/products/${p.id}`}>Review</Link>;
      return <Link href={`/products/${p.id}`}>View</Link>;
    } }),
  ], [rows, selected]);

  const table = useReactTable({ data: rows, columns, state: { sorting }, onSortingChange: setSorting, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(), getFilteredRowModel: getFilteredRowModel() });

  if (cat.error) return <ErrorBox error={cat.error} onRetry={cat.reload} />;
  if (!cat.data) return <LoadingBlock label="Loading products" />;
  const { summary: s } = cat.data;
  const chosen = sanitizeSelection(selected, products);

  // Products the AI has not been asked about yet (an import whose recommendation run was interrupted, a new product from a sync that could not get one): one button finishes the batch.
  const missing = products.filter((p) => p.band === null && p.review_status === "not_reviewed");
  async function recommendMissing() {
    const todo = missing.map((p) => p.id);
    setRecRun({ done: 0, total: todo.length });
    for (const [i, id] of todo.entries()) {
      try { await api.recommend(id); } catch { /* the row stays "No recommendation yet" and can be retried from its page */ }
      setRecRun({ done: i + 1, total: todo.length });
      cat.reload();
    }
    setRecRun(null);
  }

  async function bulk() {
    setBusy(true); setMsg(null);
    try {
      const fp = (await api.getProduct(chosen[0])).fine_print_version;
      const r = await api.bulkAccept({ product_ids: chosen, fine_print_version: fp });
      setMsg(`Accepted ${r.accepted.length}.${r.rejected.length ? ` ${r.rejected.length} skipped: only High-confidence products can be bulk accepted.` : ""}`);
      setSelected([]); cat.reload();
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <>
      <div className="page-head">
        <div><h1>Products</h1><p>Open a product to review the AI’s recommendation and accept it (once per product): then buyers abroad see duties included. To accept several at once, tick the High-confidence ones.</p></div>
        <div className="row">
          <button type="button" className="btn btn-primary" disabled={busy || chosen.length === 0} onClick={bulk}>
            {chosen.length ? `Accept ${chosen.length} recommendation${chosen.length > 1 ? "s" : ""}` : "Accept selected"}
          </button>
        </div>
      </div>
      <SyncBar onSynced={cat.reload} />
      <section aria-label="Summary" className="grid grid-3">
        <div className="card"><div className="kpi-label">Ready for duties-included</div><div className="kpi">{s.ready_count} of {s.total_count}</div><div className="kpi-label">{s.total_count === 0 ? "Nothing imported yet" : s.high_band_open > 0 ? `Accepting the ${s.high_band_open} High-confidence ${s.high_band_open === 1 ? "product" : "products"} below would make it ${s.ready_after_accept}` : "Open a product to review it, or answer its quick question"}</div></div>
        <div className="card"><div className="kpi-label">Passport stamps</div><div className="kpi">{s.passport_countries} {s.passport_countries === 1 ? "country" : "countries"}</div><Link className="kpi-label" href="/passport">See your passport</Link></div>
        <div className="card" style={{ background: "var(--orange-tint)", borderColor: "#f0cdb8" }}>
          <div className="kpi-label" style={{ color: "var(--orange-ink)", fontWeight: 600 }}>Rule Radar</div>
          <div className="kpi" style={{ color: "var(--orange-ink)" }}>{s.radar_next_days === null ? "None" : `${s.radar_next_days} days`}</div>
          <Link className="kpi-label" style={{ color: "var(--orange-ink)" }} href="/radar">Next change affects {s.radar_next_affects} products</Link>
        </div>
      </section>
      {msg && <div className="note-bar" role="status">{msg}</div>}
      {missing.length > 0 && (
        <div className="note-bar" role="status" style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", justifyContent: "space-between" }}>
          <span>{recRun ? `Reading product ${Math.min(recRun.done + 1, recRun.total)} of ${recRun.total}…` : `${missing.length} product${missing.length === 1 ? " has" : "s have"} no recommendation yet. The AI reads each listing and its photos (about 10 seconds each).`}</span>
          <button type="button" className="btn btn-primary btn-sm" disabled={!!recRun} onClick={recommendMissing}>{recRun ? "Working…" : `Get ${missing.length === 1 ? "the recommendation" : "recommendations"}`}</button>
        </div>
      )}
      <section className="card" aria-label="Product list">
        <div className="row" role="group" aria-label="Filter by status" style={{ padding: "4px 0 10px" }}>
          {FILTERS.map(([k, label]) => <button key={k} type="button" className={`btn btn-sm ${filter === k ? "btn-primary" : "btn-ghost"}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>{label}</button>)}
        </div>
        {rows.length === 0 ? (s.total_count === 0
          ? <Empty title="No products yet">Landfall reads the product feed of the store you connect. <Link href="/connect">Connect your store&apos;s feed</Link>, or press Sync now above if it is already connected.</Empty>
          : <Empty title="Nothing here">No products match this filter. <button type="button" className="btn btn-ghost btn-sm" onClick={() => setFilter("all")}>Show all products</button></Empty>) : (
          <div className="tablewrap" tabIndex={0} role="region" aria-label="Products table">
            <table className="t">
              <thead>{table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>{hg.headers.map((h) => (
                  <th key={h.id} aria-sort={h.column.getIsSorted() === "asc" ? "ascending" : h.column.getIsSorted() === "desc" ? "descending" : undefined}>
                    {h.column.getCanSort() ? <button type="button" onClick={h.column.getToggleSortingHandler()}>{flexRender(h.column.columnDef.header, h.getContext())}{{ asc: " ▲", desc: " ▼" }[h.column.getIsSorted() as string] ?? ""}</button> : flexRender(h.column.columnDef.header, h.getContext())}
                  </th>))}</tr>))}</thead>
              <tbody>{table.getRowModel().rows.map((r) => (
                <tr key={r.id}>{r.getVisibleCells().map((c) => <td key={c.id}>{flexRender(c.column.columnDef.cell, c.getContext())}</td>)}</tr>))}</tbody>
            </table>
          </div>
        )}
      </section>
      <p className="fineprint">You are responsible for the customs declaration on every accepted product; you can override at any time. Only High-confidence rows can be accepted in bulk.</p>
    </>
  );
}
