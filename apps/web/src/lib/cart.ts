"use client";
import { useMemo, useSyncExternalStore } from "react";

export interface CartLine { id: string; qty: number }
const CART_KEY = "landfall.cart.v1";
const SHIP_KEY = "landfall.ship.v1";
export const MAX_QTY = 99;

function write(key: string, v: unknown): void {
  try { window.localStorage.setItem(key, JSON.stringify(v)); window.dispatchEvent(new Event("landfall-cart")); } catch { /* private mode: the cart lives for this page only */ }
}

/** Keep only well-formed lines: a hand-edited or old cart never breaks the page. */
export function cleanCart(raw: unknown): CartLine[] {
  if (!Array.isArray(raw)) return [];
  const out: CartLine[] = [];
  for (const l of raw) {
    if (l && typeof l.id === "string" && Number.isInteger(l.qty) && l.qty >= 1) {
      const have = out.find((x) => x.id === l.id);
      if (have) have.qty = Math.min(MAX_QTY, have.qty + l.qty); else out.push({ id: l.id, qty: Math.min(MAX_QTY, l.qty) });
    }
  }
  return out;
}

/** "p_mug:2,p_bowl:1" (the checkout link form) to lines. */
export function parseItems(s: string | null): CartLine[] {
  if (!s) return [];
  return cleanCart(s.split(",").map((x) => { const [id, q] = x.split(":"); return { id: id ?? "", qty: Number(q ?? "1") }; }));
}

function subscribe(cb: () => void): () => void {
  window.addEventListener("landfall-cart", cb); window.addEventListener("storage", cb);
  return () => { window.removeEventListener("landfall-cart", cb); window.removeEventListener("storage", cb); };
}
const rawOf = (key: string) => () => { try { return window.localStorage.getItem(key) ?? ""; } catch { return ""; } };
const cartRaw = rawOf(CART_KEY);
const shipRaw = rawOf(SHIP_KEY);
const never = () => () => {};

export function useCart() {
  const rawCart = useSyncExternalStore(subscribe, cartRaw, () => "");
  const rawShip = useSyncExternalStore(subscribe, shipRaw, () => "");
  const ready = useSyncExternalStore(never, () => true, () => false);
  const lines = useMemo(() => { try { return cleanCart(rawCart ? JSON.parse(rawCart) : []); } catch { return []; } }, [rawCart]);
  const ship = useMemo(() => { try { return rawShip ? (JSON.parse(rawShip) as string) : "US"; } catch { return "US"; } }, [rawShip]);
  const set = (next: CartLine[]) => write(CART_KEY, next);
  // Always start from what is stored right now, never from the last render: two quick clicks must both count.
  const now = (): CartLine[] => { try { const r = cartRaw(); return cleanCart(r ? JSON.parse(r) : []); } catch { return []; } };
  return {
    lines, ship, ready,
    add: (id: string, qty = 1) => set(cleanCart([...now(), { id, qty }])),
    setQty: (id: string, qty: number) => set(qty < 1 ? now().filter((l) => l.id !== id) : now().map((l) => (l.id === id ? { ...l, qty: Math.min(MAX_QTY, qty) } : l))),
    remove: (id: string) => set(now().filter((l) => l.id !== id)),
    clear: () => set([]),
    setShip: (c: string) => write(SHIP_KEY, c),
  };
}
