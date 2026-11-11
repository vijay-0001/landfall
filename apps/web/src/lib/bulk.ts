import type { Product } from "@/lib/api/models";

/**
 * Bulk accept is for the High band only (FR-13). Check and Ask rows, rows with open questions,
 * rows already reviewed, and rows where duties-included is paused (T5) can never be selected.
 */
export function bulkBlockReason(p: Product): string | null {
  if (p.review_status !== "not_reviewed") return "Already reviewed";
  if (p.paused_reason) return "Not available for duties-included";
  if (p.question_count > 0) return "Answer the questions first";
  if (p.band !== "high") return p.band === "check" ? "Check this one on its own" : "Needs your answers";
  return null;
}

export function isBulkEligible(p: Product): boolean {
  return bulkBlockReason(p) === null;
}

export function eligibleIds(products: Product[]): string[] {
  return products.filter(isBulkEligible).map((p) => p.id);
}

/** Drop anything from a selection that is not eligible (stale selections, tampering). */
export function sanitizeSelection(selected: Iterable<string>, products: Product[]): string[] {
  const ok = new Set(eligibleIds(products));
  return [...selected].filter((id) => ok.has(id));
}
