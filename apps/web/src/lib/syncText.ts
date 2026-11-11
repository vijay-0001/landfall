import type { SyncOut } from "@/lib/api/models";

const n = (k: number, one: string, many: string) => `${k} ${k === 1 ? one : many}`;

/** What a sync did, in plain words: only what happened is mentioned, and "nothing changed" is said as that. */
export function syncSentence(s: SyncOut): string {
  const parts: string[] = [];
  if (s.added) parts.push(`${n(s.added, "new product was", "new products were")} added${s.recommended ? " and recommended" : ""}`);
  if (s.price_updated) parts.push(`${n(s.price_updated, "price was", "prices were")} updated (your decisions stand)`);
  if (s.changed) parts.push(`${n(s.changed, "product was", "products were")} changed in your store, so ${s.changed === 1 ? "it needs" : "they need"} your review again`);
  if (s.removed) parts.push(`${n(s.removed, "product left", "products left")} your feed and ${s.removed === 1 ? "is" : "are"} no longer sold through the checkout`);
  if (s.restored) parts.push(`${n(s.restored, "product is", "products are")} back in your feed`);
  const head = parts.length ? `${parts.join("; ")}.` : "Nothing changed since the last sync.";
  return s.pending ? `${head} ${n(s.pending, "product", "products")} could not get a recommendation yet: open ${s.pending === 1 ? "it" : "each"} to try again.` : head;
}
