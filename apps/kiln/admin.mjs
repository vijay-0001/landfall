// Kiln & Co.'s back office: how a merchant adds a product, uploads photos and edits or removes it. This belongs to the MERCHANT, not to Landfall:
// products live in Kiln's own catalogue file, photos are stored on Kiln's own server, and Landfall only ever sees them through Kiln's public product feed.
// Staff sign in with KILN_ADMIN_USER and KILN_ADMIN_PASSWORD (a mock login: one shared account, no reset, no buyer accounts). The back office is OFF unless a password of at least 10 characters is set.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

export const CURRENCIES = ["GBP", "USD", "EUR", "AUD"];  // the four destinations Landfall prices: US, UK, EU, Australia
export const MAX_PHOTOS = 4;
export const MAX_PHOTO_BYTES = 2 * 1024 * 1024;
const SKU = /^[A-Z0-9][A-Z0-9-]{2,23}$/;

/** The image type from the file's own first bytes (a browser's file name or type is not trusted). */
export function sniff(b) {
  if (b.length > 12 && b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return { ext: ".jpg", type: "image/jpeg" };
  if (b.length > 12 && b.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return { ext: ".png", type: "image/png" };
  if (b.length > 12 && b.subarray(0, 4).toString("latin1") === "RIFF" && b.subarray(8, 12).toString("latin1") === "WEBP") return { ext: ".webp", type: "image/webp" };
  return null;
}

class Refusal extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const plain = (html) => String(html ?? "").replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/\s+/g, " ").trim();
const priceOf = (p, cur) => p.variants[0].presentment_prices.find((x) => x.price.currency_code === cur)?.price.amount ?? "";

export function createAdmin({ dataDir, seedPath, user = "owner", password = "" }) {
  const enabled = typeof password === "string" && password.length >= 10;
  const secret = crypto.randomBytes(32);  // sessions end when Kiln restarts
  const SESSION_MS = 8 * 60 * 60 * 1000;
  const fails = new Map();  // ip -> [timestamps]: five wrong passwords a minute, then wait
  const digest = (s) => crypto.createHash("sha256").update(String(s)).digest();
  const sameText = (a, b) => crypto.timingSafeEqual(digest(a), digest(b));
  const mac = (s) => crypto.createHmac("sha256", secret).update(s).digest("base64url");

  function cookieOf(req) {
    const m = /(?:^|;\s*)kiln_session=([A-Za-z0-9_.-]+)/.exec(req.headers.cookie ?? "");
    return m ? m[1] : "";
  }
  /** True when the request carries a valid, unexpired staff session. */
  function signedIn(req) {
    if (!enabled) return false;
    const [body, sig] = cookieOf(req).split(".");
    if (!body || !sig || !sameText(sig, mac(body))) return false;
    try { return JSON.parse(Buffer.from(body, "base64url").toString()).exp > Date.now(); } catch { return false; }
  }
  const sessionCookie = (req, value, maxAge) =>
    `kiln_session=${value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${maxAge}${req.headers["x-forwarded-proto"] === "https" ? "; Secure" : ""}`;

  const file = path.join(dataDir, "catalogue.json");
  const uploads = path.join(dataDir, "uploads");

  function load() {
    if (!enabled) return JSON.parse(fs.readFileSync(seedPath, "utf8"));  // without the back office the shop is exactly the seed catalogue
    if (!fs.existsSync(file)) { fs.mkdirSync(dataDir, { recursive: true }); fs.copyFileSync(seedPath, file); }
    return JSON.parse(fs.readFileSync(file, "utf8"));
  }
  function save(c) {
    fs.mkdirSync(dataDir, { recursive: true });
    fs.writeFileSync(file + ".tmp", JSON.stringify(c, null, 2));
    fs.renameSync(file + ".tmp", file);
  }

  function fields(b, { create }) {
    const title = String(b?.title ?? "").replace(/\s+/g, " ").trim();
    const description = String(b?.description ?? "").replace(/\s+/g, " ").trim();
    if (title.length < 3 || title.length > 120) throw new Refusal(422, "The title must be 3 to 120 characters.");
    if (description.length < 10 || description.length > 2000) throw new Refusal(422, "The description must be 10 to 2000 characters. Say what it is made of and where it is made.");
    const prices = {};
    for (const cur of CURRENCIES) {
      const v = String(b?.prices?.[cur] ?? "").trim();
      if (!/^\d{1,7}(\.\d{1,2})?$/.test(v) || Number(v) <= 0) throw new Refusal(422, `The ${cur} price must be a positive number with at most 2 decimals, like 38.00.`);
      prices[cur] = Number(v).toFixed(2);
    }
    let sku = String(b?.sku ?? "").trim().toUpperCase();
    if (create) {
      if (!sku) sku = title.toUpperCase().replace(/[^A-Z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 14) + "-" + String(Math.floor(100 + Math.random() * 900));
      if (!SKU.test(sku)) throw new Refusal(422, "The SKU must be 3 to 24 letters, numbers or dashes.");
    }
    return { title, description, prices, sku };
  }

  /** Decode and store uploaded photos; returns their public paths. Nothing is stored unless every photo is a real image. */
  function storePhotos(list) {
    if (list === undefined || list === null) return [];
    if (!Array.isArray(list)) throw new Refusal(422, "Photos must be a list.");
    const decoded = list.map((p, i) => {
      const data = typeof p?.data === "string" ? p.data.replace(/^data:[^,]*,/, "") : "";
      const buf = Buffer.from(data, "base64");
      if (!buf.length) throw new Refusal(422, `Photo ${i + 1} is empty.`);
      if (buf.length > MAX_PHOTO_BYTES) throw new Refusal(422, `Photo ${i + 1} is larger than 2 MB.`);
      const kind = sniff(buf);
      if (!kind) throw new Refusal(422, `Photo ${i + 1} is not a JPEG, PNG or WebP image.`);
      return { buf, kind };
    });
    fs.mkdirSync(uploads, { recursive: true });
    return decoded.map(({ buf, kind }) => {
      const name = crypto.randomBytes(8).toString("hex") + kind.ext;
      fs.writeFileSync(path.join(uploads, name), buf);
      return "/uploads/" + name;
    });
  }

  const row = (p) => ({ sku: p.variants[0].sku, title: p.title, description: plain(p.body_html), prices: Object.fromEntries(CURRENCIES.map((c) => [c, priceOf(p, c)])), images: p.images ?? [] });

  function variantsFor(sku, prices) {
    return [{ sku, title: "Default Title", price: prices.GBP, presentment_prices: CURRENCIES.map((c) => ({ price: { amount: prices[c], currency_code: c } })) }];
  }

  /** Returns true when it answered the request. */
  async function handle(req, res, u, { send, readBody }) {
    const isApi = u.pathname.startsWith("/api/admin/");
    const isUpload = u.pathname.startsWith("/uploads/");
    if (!isApi && !isUpload) return false;
    if (!enabled) { send(res, 404, { detail: "Not found" }); return true; }
    try {
      if (isApi && u.pathname === "/api/admin/login" && req.method === "POST") {
        const ip = req.socket.remoteAddress ?? "?";
        const recent = (fails.get(ip) ?? []).filter((t) => Date.now() - t < 60_000);
        if (recent.length >= 5) { send(res, 429, { detail: "Too many wrong passwords. Wait a minute and try again." }); return true; }
        const b = await readBody(req, 2000);
        if (sameText(b?.user ?? "", user) && sameText(b?.password ?? "", password)) {
          fails.delete(ip);
          const body = Buffer.from(JSON.stringify({ u: user, exp: Date.now() + SESSION_MS })).toString("base64url");
          res.writeHead(200, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "Set-Cookie": sessionCookie(req, `${body}.${mac(body)}`, SESSION_MS / 1000) });
          res.end(JSON.stringify({ signedIn: true }));
        } else {
          fails.set(ip, [...recent, Date.now()]);
          send(res, 401, { detail: "That user name or password is not right." });
        }
        return true;
      }
      if (isApi && u.pathname === "/api/admin/logout" && req.method === "POST") {
        res.writeHead(200, { "Content-Type": "application/json; charset=utf-8", "Set-Cookie": sessionCookie(req, "", 0) });
        res.end(JSON.stringify({ signedIn: false }));
        return true;
      }
      if (isApi && u.pathname === "/api/admin/session" && req.method === "GET") { send(res, 200, { signedIn: signedIn(req) }); return true; }
      if (isApi && !signedIn(req)) { send(res, 401, { detail: "Sign in to the shop admin first." }); return true; }
      if (isUpload && req.method === "GET") {
        const m = /^\/uploads\/([a-f0-9]{16}\.(jpg|png|webp))$/.exec(u.pathname);
        const f = m && path.join(uploads, m[1]);
        if (!f || !fs.existsSync(f)) { send(res, 404, { detail: "Not found" }); return true; }
        const type = { jpg: "image/jpeg", png: "image/png", webp: "image/webp" }[m[2]];
        send(res, 200, fs.readFileSync(f), type);
        return true;
      }
      if (req.method === "GET" && u.pathname === "/api/admin/products") { send(res, 200, { products: load().products.map(row) }); return true; }
      const body = ["POST", "PUT"].includes(req.method) ? await readBody(req, 12 * 1024 * 1024) : null;
      const cat = load();
      if (req.method === "POST" && u.pathname === "/api/admin/products") {
        const f = fields(body, { create: true });
        if (cat.products.some((p) => p.variants[0].sku === f.sku)) throw new Refusal(409, `A product with SKU ${f.sku} already exists.`);
        if ((body.photos ?? []).length > MAX_PHOTOS) throw new Refusal(422, `At most ${MAX_PHOTOS} photos per product.`);
        const images = storePhotos(body.photos);
        const id = Math.max(0, ...cat.products.map((p) => p.id ?? 0)) + 1;
        const product = { id, handle: f.sku.toLowerCase(), title: f.title, body_html: `<p>${esc(f.description)}</p>`, variants: variantsFor(f.sku, f.prices), images };
        cat.products.push(product);
        save(cat);
        send(res, 201, { product: row(product) });
        return true;
      }
      const m = /^\/api\/admin\/products\/([A-Za-z0-9-]{3,24})$/.exec(u.pathname);
      if (m && ["PUT", "DELETE"].includes(req.method)) {
        const i = cat.products.findIndex((p) => p.variants[0].sku === m[1].toUpperCase());
        if (i < 0) throw new Refusal(404, "No product with that SKU.");
        if (req.method === "DELETE") { const [gone] = cat.products.splice(i, 1); save(cat); send(res, 200, { removed: row(gone) }); return true; }
        const p = cat.products[i];
        const f = fields(body, { create: false });
        const keep = (Array.isArray(body.keep) ? body.keep : (p.images ?? [])).filter((x) => (p.images ?? []).includes(x));  // only photos the product already has
        if (keep.length + (body.photos ?? []).length > MAX_PHOTOS) throw new Refusal(422, `At most ${MAX_PHOTOS} photos per product.`);
        const added = storePhotos(body.photos);
        p.title = f.title;
        p.body_html = `<p>${esc(f.description)}</p>`;
        p.variants = variantsFor(p.variants[0].sku, f.prices);
        p.images = [...keep, ...added];
        save(cat);
        send(res, 200, { product: row(p) });
        return true;
      }
      send(res, 404, { detail: "Not found" });
      return true;
    } catch (e) {
      if (e instanceof Refusal) send(res, e.code, { detail: e.message });
      else send(res, e?.message === "too large" ? 413 : 400, { detail: e?.message === "too large" ? "That upload is too large." : "That request could not be read." });
      return true;
    }
  }

  return { enabled, load, handle, signedIn };
}
