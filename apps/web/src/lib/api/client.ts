// Typed API client: one function per endpoint in the OpenAPI contract. Every call goes to the real backend at /api.
import type {
  AnswerIn, AnswerOut, BulkAcceptIn, BulkAcceptOut, Catalogue, Decision, DecisionIn, Destination, HowItWorks,
  OrderCaptured, OrderCreated, OrderCreateIn, OrderReceipt, Storefront, AssistantReply, Passport, Product, ProductCreate, ProductDetail, Quote, QuoteIn, RadarAlert, RadarChoiceIn,
  RuleEditIn, RuleProposal, SyncStatus, Coverage, TimeMachineOptions, TimeMachineSeries, ImportIn, ImportOut, SyncOut, MerchantCreate, MerchantCreated, MerchantMe,
} from "./models";
import { ApiError } from "./errors";
import { getKey } from "../merchant";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

/** FastAPI sends a string for our own refusals and a list of {loc, msg} for a field that failed validation: both become one plain sentence (never "[object Object]"). */
export function plainDetail(d: unknown): string | undefined {
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    const parts = d.map((e) => {
      const m = e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg).replace(/^Value error, /, "") : null;
      const loc = e && typeof e === "object" && "loc" in e && Array.isArray((e as { loc: unknown[] }).loc) ? String((e as { loc: unknown[] }).loc.at(-1)) : "";
      return m ? (loc && loc !== "body" ? `${loc.replace(/_/g, " ")}: ${m}` : m) : null;
    }).filter(Boolean);
    return parts.length ? parts.join("; ") : undefined;
  }
  return undefined;
}

async function http<T>(method: string, path: string, body?: unknown): Promise<T> {
  const key = getKey();
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (key) headers.Authorization = `Bearer ${key}`;  // the merchant's own key: without one the console shows the demo merchant
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: Object.keys(headers).length ? headers : undefined,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = plainDetail((await res.json()).detail) ?? detail; } catch { /* not json */ }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

/** Does Landfall know this key? Asked before a pasted key is kept, so a typo or a key from another deployment is caught at once. */
export async function keyIsKnown(key: string): Promise<boolean | null> {
  try {
    const r = await fetch(`${BASE}/merchants/me`, { headers: { Authorization: `Bearer ${key}` }, cache: "no-store" });
    return r.status === 401 ? false : r.ok ? true : null;  // null: Landfall could not be asked
  } catch { return null; }
}

export const api = {
  getCatalogue: () => http<Catalogue>("GET", "/catalogue"),
  getProduct: (id: string) => http<ProductDetail>("GET", `/products/${id}`),
  answer: (recId: string, b: AnswerIn) => http<AnswerOut>("POST", `/recommendations/${recId}/answer`, b),
  decide: (recId: string, b: DecisionIn) => http<Decision>("POST", `/recommendations/${recId}/decision`, b),
  bulkAccept: (b: BulkAcceptIn) => http<BulkAcceptOut>("POST", "/products/bulk-accept", b),
  postQuote: (b: QuoteIn) => http<Quote>("POST", "/quote", b),
  createOrder: (b: OrderCreateIn) => http<OrderCreated>("POST", "/orders", b),
  getAssistant: (id: string) => http<AssistantReply[]>("GET", `/products/${id}/assistant`),
  askAssistant: (id: string, question: string) => http<AssistantReply>("POST", `/products/${id}/assistant`, { question }),
  getShop: () => http<Storefront>("GET", "/shop"),
  getOrder: (id: string) => http<OrderReceipt>("GET", `/orders/${id}`),
  captureOrder: (id: string) => http<OrderCaptured>("POST", `/orders/${id}/capture`),
  getTimeMachineOptions: () => http<TimeMachineOptions>("GET", "/timemachine/options"),
  getTimeMachineSeries: (product: string, origin: string, destination: Destination) =>
    http<TimeMachineSeries>("GET", `/timemachine/series?product=${encodeURIComponent(product)}&origin=${encodeURIComponent(origin)}&destination=${destination}`),
  getRadar: () => http<RadarAlert[]>("GET", "/radar"),
  radarChoice: (id: string, b: RadarChoiceIn) => http<RadarAlert>("POST", `/radar/${id}/choice`, b),
  getPassport: () => http<Passport>("GET", "/passport"),
  getSync: () => http<SyncStatus>("GET", "/ops/sync"),
  getCoverage: () => http<Coverage>("GET", "/coverage"),
  getRules: () => http<RuleProposal[]>("GET", "/ops/rules"),
  ruleAction: (id: string, action: "approve" | "edit" | "reject", edit?: RuleEditIn) => http<RuleProposal>("POST", `/ops/rules/${id}/${action}`, edit ?? {}),
  getHowItWorks: () => http<HowItWorks>("GET", "/how-it-works"),
  createProduct: (b: ProductCreate) => http<Product>("POST", "/products", b),
  recommend: (id: string) => http<ProductDetail>("POST", `/products/${id}/recommend`),
  createMerchant: (b: MerchantCreate) => http<MerchantCreated>("POST", "/merchants", b),
  getMe: () => http<MerchantMe>("GET", "/merchants/me"),
  importFeed: (b: ImportIn) => http<ImportOut>("POST", "/products/import", b),
  syncFeed: () => http<SyncOut>("POST", "/products/sync"),
};

/** URL of the server-rendered share image for a Time Machine view. Built here so pages and og:image agree. */
export function shareImageUrl(p: { product: string; origin: string; destination: string; date?: string }): string {
  const q = new URLSearchParams({ product: p.product, origin: p.origin, destination: p.destination });
  if (p.date) q.set("date", p.date);
  return `${BASE}/timemachine/share.png?${q.toString()}`;
}
