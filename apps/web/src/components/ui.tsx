"use client";
import Link from "next/link";
import type { ReactNode } from "react";
import type { Band, Money, Product } from "@/lib/api/models";
import { clearKey } from "@/lib/merchant";
import { formatMoney } from "@/lib/money";

export function Logo({ color = "#7FD1C7", size = 24 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="4" y="3" width="16" height="18" rx="2" /><circle cx="12" cy="10" r="3.5" /><path d="M8 17h8" />
    </svg>
  );
}

export function Amount({ m, signed }: { m: Money | null | undefined; signed?: boolean }) {
  if (!m) return <span className="muted">–</span>;
  return <span className="mono">{formatMoney(m, { signed })}</span>;
}

export function Skeleton({ h = 16, w = "100%" }: { h?: number; w?: string | number }) {
  return <div className="skel" style={{ height: h, width: w }} aria-hidden="true" />;
}

export function LoadingBlock({ label = "Loading" }: { label?: string }) {
  return (
    <div className="stack" role="status" aria-live="polite" aria-label={label}>
      <Skeleton h={28} w="40%" /><Skeleton h={90} /><Skeleton h={90} /><span className="sr-only">{label}…</span>
    </div>
  );
}

export function ErrorBox({ error, onRetry, title = "That did not load." }: { error: Error; onRetry?: () => void; title?: string }) {
  return (
    <div className="errbox" role="alert">
      <div style={{ flex: 1, minWidth: 220 }}><b>{title}</b><div className="fineprint" style={{ color: "inherit" }}>{error.message}</div></div>
      {(error as { status?: number }).status === 401
        ? <Link href="/connect" className="btn btn-warn btn-sm" onClick={() => clearKey()}>Sign in again</Link>  // a saved key Landfall no longer knows: forget it and go where a new one is entered
        : (error as { status?: number }).status === 404
          ? <Link href="/products" className="btn btn-warn btn-sm">Back to products</Link>
          : onRetry && <button type="button" className="btn btn-warn btn-sm" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><b style={{ color: "var(--ink)" }}>{title}</b><div>{children}</div></div>;
}

const BAND_LABEL: Record<Band, string> = { high: "High confidence", check: "Check", ask: "Needs your answer" };
export function BandBadge({ band }: { band: Band }) {
  return <span className={`badge ${band === "high" ? "ok" : "warn"}`}>{BAND_LABEL[band]}</span>;
}

/** Status shown in the catalogue. "Recommended" = the AI has proposed and the seller has not decided. */
export function statusOf(p: Product): { label: string; cls: string } {
  if (p.listing_changed) return { label: "Changed: review again", cls: "warn" };  // the store changed the listing after the seller decided
  if (p.band === null || p.band === undefined) return { label: "No recommendation yet", cls: "warn" };
  if (p.paused_reason) return { label: p.paused_reason.startsWith("Landfall will not price this") ? "Landfall won't price this" : "Needs a code from you", cls: "warn" };  // refused goods, or no code Landfall could match: the seller can enter one with Override
  if (p.review_status === "accepted") return { label: "Accepted", cls: "ok" };
  if (p.review_status === "overridden") return { label: "Overridden", cls: "ok" };
  if (p.question_count > 0) return { label: p.question_count === 1 ? "1 quick question" : `${p.question_count} quick questions`, cls: "warn" };
  return { label: "Recommended", cls: "info" };
}

/** Landfall prices four destinations (US, UK, EU, Australia): a price in any other currency is never shown, so no one wonders what it is for. */
export const SHOWN_CURRENCIES = ["USD", "GBP", "EUR", "AUD"] as const;
export const SYMBOLS: Record<string, string> = { GBP: "£", USD: "$", EUR: "€", AUD: "A$" };
export function priceLine(prices: Record<string, string>): string {
  return SHOWN_CURRENCIES.filter((c) => prices[c]).map((c) => `${SYMBOLS[c]}${prices[c]}`).join(" · ");
}

export const ORIGIN_LABEL: Record<string, string> = {
  GB: "United Kingdom", US: "United States", CN: "China", IN: "India", PT: "Portugal", DE: "Germany", FR: "France", EU: "European Union",
};
export function countryName(c: string): string {
  if (c === "other") return "A country Landfall does not price yet";
  if (ORIGIN_LABEL[c]) return ORIGIN_LABEL[c];
  try { return new Intl.DisplayNames(["en"], { type: "region" }).of(c) ?? c; } catch { return c; } // any ISO code, not only the register's
}
export const originLabel = (c: string | null | undefined, uncertain = false) =>
  c ? `${countryName(c)}${uncertain ? "?" : ""}` : "–";
/** The recommendation says "none" when the product is outside what Landfall prices. */
export const isNotCovered = (code: string | null | undefined) => code === "none";

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}
