"use client";
import { useState } from "react";
import { api } from "@/lib/api/client";
import type { MerchantMe, SyncOut } from "@/lib/api/models";
import { getKey } from "@/lib/merchant";
import { useAsync } from "@/lib/hooks";
import { syncSentence } from "@/lib/syncText";

/** "Last synced / Sync now" for the connected store's product feed, shown on the Products page so the button is where the products are. */
export function SyncBar({ onSynced }: { onSynced: () => void }) {
  const me = useAsync<MerchantMe | null>(() => (getKey() ? api.getMe().catch(() => null) : Promise.resolve(null)), "syncbar-me");
  const [res, setRes] = useState<SyncOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!me.data?.feed_url) return null;
  const at = res?.last_synced_at ?? me.data.last_synced_at;
  const when = at ? new Date(at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC" : null;
  async function sync() {
    if (busy) return;
    setBusy(true); setErr(null);
    try { setRes(await api.syncFeed()); me.reload(); onSynced(); } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  }
  return (
    <section className="card" aria-label="Product feed sync" style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", justifyContent: "space-between", padding: "12px 18px" }}>
      <span style={{ minWidth: 0 }}>
        Synced with <span className="mono" style={{ overflowWrap: "anywhere" }}>{me.data.feed_url}</span>. <b id="sync-when">{when ? `Last synced ${when}.` : "Not synced yet."}</b> Landfall also syncs every night.
      </span>
      <button type="button" className="btn btn-primary" onClick={sync} disabled={busy}>{busy ? "Syncing…" : "Sync now"}</button>
      {err && <div className="note-bar stop" role="alert" style={{ flexBasis: "100%" }}>{err}</div>}
      {res && (
        <div className="note-bar" role="status" id="sync-result-bar" style={{ flexBasis: "100%" }}>
          {syncSentence(res)}
        </div>
      )}
    </section>
  );
}
