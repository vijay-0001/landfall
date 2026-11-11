import type { Currency, Money } from "@/lib/api/models";

// Money is a decimal string plus currency. We never convert currency, and we never use floats for amounts.

const SYMBOL: Record<Currency, string> = { USD: "$", GBP: "£", EUR: "€", AUD: "A$", CAD: "C$" };

/** Parse a decimal string such as "7.60" or "-0.8" into minor units (cents) without floating point. */
export function toMinor(amount: string): number {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(amount.trim());
  if (!m) throw new Error(`Not a decimal amount: ${amount}`);
  const [, sign, whole, frac = ""] = m;
  const cents = Number(whole) * 100 + Number((frac + "00").slice(0, 2));
  // Round half up on a third decimal, if one was supplied.
  const bump = frac.length > 2 && Number(frac[2]) >= 5 ? 1 : 0;
  return (sign ? -1 : 1) * (cents + bump);
}

export function fromMinor(minor: number, currency: Currency): Money {
  const sign = minor < 0 ? "-" : "";
  const abs = Math.abs(minor);
  const whole = Math.floor(abs / 100);
  const cents = String(abs % 100).padStart(2, "0");
  return { amount: `${sign}${whole}.${cents}`, currency };
}

export function money(amount: string, currency: Currency): Money {
  return { amount, currency };
}

export function addMoney(...items: Money[]): Money {
  if (items.length === 0) throw new Error("addMoney needs at least one amount");
  const currency = items[0].currency;
  let total = 0;
  for (const i of items) {
    if (i.currency !== currency) throw new Error("Landfall never converts currency: cannot add " + i.currency + " to " + currency);
    total += toMinor(i.amount);
  }
  return fromMinor(total, currency);
}

export function subMoney(a: Money, b: Money): Money {
  return addMoney(a, { amount: fromMinor(-toMinor(b.amount), b.currency).amount, currency: b.currency });
}

export function isZero(m: Money): boolean {
  return toMinor(m.amount) === 0;
}

export function groupThousands(whole: string): string {
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** "$7.60", "£30.00", "€3.00". With `signed`, "+$3.90" or "-$0.70". Currency symbol only; code via `withCode`. */
export function formatMoney(m: Money, opts: { signed?: boolean; withCode?: boolean } = {}): string {
  const minor = toMinor(m.amount);
  const abs = Math.abs(minor);
  const whole = groupThousands(String(Math.floor(abs / 100)));
  const cents = String(abs % 100).padStart(2, "0");
  const sign = minor < 0 ? "-" : opts.signed ? "+" : "";
  const body = `${sign}${SYMBOL[m.currency]}${whole}.${cents}`;
  return opts.withCode ? `${body} ${m.currency}` : body;
}

/** Whole amounts without cents, for compact UI such as axis ticks: "$45". */
export function formatMoneyShort(m: Money): string {
  const minor = toMinor(m.amount);
  const sign = minor < 0 ? "-" : "";
  return `${sign}${SYMBOL[m.currency]}${groupThousands(String(Math.round(Math.abs(minor) / 100)))}`;
}

export function currencySymbol(c: Currency): string {
  return SYMBOL[c];
}
