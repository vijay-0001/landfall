// Kiln & Co. storefront script. No framework, no build. Text is always set with textContent, never as HTML.
(() => {
  const $ = (s) => document.querySelector(s);
  const store = {
    get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode: the cart lives for this page only */ } },
  };
  const calls = {
    all() { try { return JSON.parse(sessionStorage.getItem("kiln_calls")) ?? []; } catch { return []; } },
    add(x) { try { sessionStorage.setItem("kiln_calls", JSON.stringify([...calls.all(), x].slice(-8))); } catch { /* ignore */ } },
    clear() { try { sessionStorage.removeItem("kiln_calls"); } catch { /* ignore */ } },
    /** Only the latest quote is kept: the panel shows this checkout, not every earlier visit. */
    addQuote(x) { try { sessionStorage.setItem("kiln_calls", JSON.stringify([...calls.all().filter((c) => c.path !== "/api/quote"), x].slice(-8))); } catch { /* ignore */ } },
  };
  const h = (tag, attrs = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return e;
  };
  const SYM = { USD: "$", GBP: "£", EUR: "€", AUD: "A$", CAD: "C$" };
  const fmt = (cur, amount) => `${SYM[cur] ?? cur + " "}${Number(amount).toFixed(2)}`;

  let countries = [];
  let feed = [];
  let known = {};
  let knownOk = false;     // true when Landfall answered (an empty answer is real: nothing synced yet), false when it could not be asked
  let ship = store.get("kiln_ship", "US");
  let cart = store.get("kiln_cart", []);

  const country = () => countries.find((c) => c.country === ship) ?? countries[0];
  const saveCart = () => { store.set("kiln_cart", cart); const n = cart.reduce((a, i) => a + i.quantity, 0); const el = $("#cartcount"); if (el) el.textContent = String(n); };
  const bySku = (sku) => { for (const p of feed) for (const v of p.variants) if (v.sku === sku) return { p, v }; return null; };
  const priceIn = (v, cur) => v.presentment_prices?.find((x) => x.price.currency_code === cur)?.price.amount ?? null;
  const refusal = (sku) => { const r = known[sku]?.paused_reason; return r && r.startsWith("Landfall will not price this") ? r : null; };
  /** What Landfall actually holds for a product, so the shop never promises more than was priced: priced, held (accepted but not priceable), pending (not decided yet), unsynced (Landfall has not read it), unknown (Landfall cannot be asked). */
  function standing(sku) {
    if (!knownOk) return "unknown";
    const k = known[sku];
    if (!k) return "unsynced";
    if (refusal(sku)) return "refused";
    if (k.review_status === "not_reviewed") return "pending";
    return k.paused_reason ? "held" : "priced";
  }
  /** Landfall's refusal text is written for the seller; the shopper gets the reason without the seller's advice, starting with a capital. */
  const shopper = (t) => { const s = t.replace(/\s*Standard checkout applies.*$/, "").replace(/^([^.]+)\.\s+(?=\1)/i, "").trim(); return s.charAt(0).toUpperCase() + s.slice(1); };
  const NOTE = {
    pending: "Import duty is not included in this price. Your carrier may bill you on delivery.",
    unsynced: "Not available to order yet. It will be after the shop's next update.",
  };

  async function jget(url) { const r = await fetch(url); return { status: r.status, json: await r.json().catch(() => null) }; }
  async function jpost(url, body) { const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); return { status: r.status, json: await r.json().catch(() => null) }; }

  // ---------------------------------------------------------------- inspector
  function callView(x, open) {
    const hl = (obj) => JSON.stringify(obj, null, 2);
    return h("details", { class: "call", open: open || undefined },
      h("summary", {}, h("span", { class: "verb" }, x.method), h("code", {}, x.path), h("span", {}, `→ ${x.status}`), h("span", { class: "ms" }, `${x.ms} ms`)),
      h("div", { class: "lbl auth" }, `Authorization: ${x.auth}`),
      x.request ? [h("div", { class: "lbl" }, /X-Landfall-Key/.test(x.auth) ? "The widget sends" : "Kiln sends"), h("pre", {}, hl(x.request))] : null,
      h("div", { class: "lbl" }, /PayPal/.test(x.auth) ? "PayPal answers" : "Landfall answers"), h("pre", {}, hl(trim(x.response))));
  }
  // The quote's trail and long text are shortened so the key facts stay readable; nothing is hidden that matters (the duty lines stay in full).
  function trim(r) {
    if (!r || typeof r !== "object") return r;
    const o = { ...r };
    if (Array.isArray(o.lines)) o.lines = o.lines.map(({ trail, ...l }) => ({ ...l, trail: trail ? `${trail.length} rate lines (the register's steps for this item)` : undefined }));
    return o;
  }
  function knownTable(skus) {
    const rows = skus.map((s) => known[s]).filter(Boolean);
    if (!rows.length) return null;
    return h("div", {}, h("div", { class: "lbl" }, "What Landfall holds for these products (accepted by the seller)"),
      h("table", { class: "known" }, h("tr", {}, ["SKU", "Status", "Code", "Origin"].map((t) => h("th", {}, t))),
        rows.map((r) => h("tr", {}, h("td", {}, r.sku), h("td", {}, r.review_status.replace("_", " ")), h("td", {}, r.code ?? "-"), h("td", {}, r.origin ?? "-")))));
  }
  function renderCalls(extra) {
    const box = $("#calls");
    if (!box) return;
    box.replaceChildren();
    const list = [...calls.all(), ...(extra ? [extra] : [])];
    const skus = cart.map((i) => i.sku);
    const kt = knownTable(skus);
    if (kt) box.append(kt);
    if (!list.length) box.append(h("p", { class: "muted" }, "Nothing asked yet. Add a product to the cart and the first call appears here."));
    list.forEach((x, i) => box.append(callView(x, i === list.length - 1)));
  }

  // ---------------------------------------------------------------- shop
  const DUTY_SENTENCE = "Import duty and taxes for the country you ship to are added at checkout and paid then, so nothing is due when the parcel arrives.";
  const productHref = (p) => `/product?h=${encodeURIComponent(p.handle ?? p.variants[0].sku.toLowerCase())}`;
  /** What the shopper is told about duty for one product, from what Landfall actually priced. Used on the shop card and on the product page. */
  function dutyBlock(p, v, price, blocked, full) {
    const st = standing(v.sku);
    if (blocked) return h("div", { class: "note warn" }, "Cannot be sold here. " + shopper(blocked.replace("Landfall will not price this: ", "")));
    if (!price) return null;
    if (st === "priced") return full
      ? h("div", { class: "note duty" }, h("span", { class: "badge" }, "Duties included"), h("p", {}, DUTY_SENTENCE))
      : [h("span", { class: "badge" }, "Duties included"), h("div", { class: "muted small" }, "Nothing to pay at the door.")];
    if (st === "held") return h("div", { class: "muted small" }, "Import duty is not included in this price. Your carrier may bill you on delivery.");
    return NOTE[st] ? h("div", { class: "muted small" }, NOTE[st]) : null;
  }
  function renderShop() {
    const grid = $("#grid");
    if (!grid) return;
    const c = country();
    grid.replaceChildren(...feed.map((p) => {
      const v = p.variants[0];
      const price = priceIn(v, c.currency);
      const blocked = refusal(v.sku);
      return h("li", { class: "item" },
        photo(p) ? gallery(p, productHref(p))
          : h("a", { class: "tile", href: productHref(p), style: `background:${p.colour ?? "#ddd"}22;color:${p.colour ?? "#555"}`, "aria-label": `${p.title}: details` }, h("span", { class: "mono" }, monogram(p.title))),
        h("div", { class: "body" }, h("h2", {}, h("a", { class: "plink", href: productHref(p) }, p.title)), h("p", {}, plain(p.body_html)),
          price ? h("div", { class: "price" }, fmt(c.currency, price)) : h("div", { class: "muted" }, `Not sold in ${c.currency}`),
          dutyBlock(p, v, price, blocked, false),
          h("button", { class: "btn", type: "button", disabled: !price || !!blocked || standing(v.sku) === "unsynced", onclick: () => add(v.sku), "aria-label": `Add ${p.title} to cart` }, "Add to cart")));
    }));
  }
  /** One product on its own page: all photos, the description, the price in the chosen country, what "Duties included" means, and Add to cart. */
  function renderProduct() {
    const box = $("#product");
    if (!box) return;
    const handle = new URLSearchParams(location.search).get("h");
    const p = feed.find((x) => (x.handle ?? x.variants[0].sku.toLowerCase()) === handle);
    if (!p) { document.title = "Not found · Kiln & Co."; box.replaceChildren(h("h1", {}, "We could not find that product"), h("p", {}, h("a", { href: "/" }, "Back to the shop"))); return; }
    document.title = `${p.title} · Kiln & Co.`;
    const v = p.variants[0], c = country(), price = priceIn(v, c.currency), blocked = refusal(v.sku);
    const list = photos(p);
    const main = list.length ? h("img", { class: "big", src: list[0], alt: p.title, width: 640, height: 480 }) : h("div", { class: "tile", style: `background:${p.colour ?? "#ddd"}22;color:${p.colour ?? "#555"}`, "aria-hidden": "true" }, h("span", { class: "mono" }, monogram(p.title)));
    const thumbs = list.length > 1 ? h("div", { class: "thumbrow" }, list.map((src, n) => h("button", { type: "button", class: "thumb", "aria-label": `Photo ${n + 1} of ${list.length} of ${p.title}`, onclick: () => { main.src = src; } }, h("img", { src, alt: "", width: 60, height: 45 })))) : null;
    box.replaceChildren(
      h("p", { class: "crumb" }, h("a", { href: "/" }, "← All products")),
      h("div", { class: "pdp" },
        h("div", { class: "pics" }, main, thumbs),
        h("div", { class: "info" }, h("h1", {}, p.title), h("p", { class: "desc" }, plain(p.body_html)),
          price ? h("div", { class: "price big-price" }, fmt(c.currency, price), h("span", { class: "muted" }, ` for ${c.name ?? c.label ?? c.country}`)) : h("div", { class: "muted" }, `Not sold in ${c.currency}`),
          dutyBlock(p, v, price, blocked, true),
          h("button", { class: "btn", type: "button", disabled: !price || !!blocked || standing(v.sku) === "unsynced", onclick: (e) => { add(v.sku); e.currentTarget.textContent = "Added. Add another"; }, "aria-label": `Add ${p.title} to cart` }, "Add to cart"),
          h("p", { class: "muted small" }, h("a", { href: "/checkout" }, "Go to your cart")))));
  }
  /** The product picture from the feed's images[0].src (Shopify's shape), by path so it loads from this shop whatever address the feed was published under. */
  const photos = (p) => (p.images ?? []).map((i) => { try { return new URL(i.src, location.href).pathname; } catch { return null; } }).filter(Boolean);
  const photo = (p) => photos(p)[0] ?? null;
  /** The main photo with a small thumbnail per extra photo; clicking a thumbnail swaps the main one. */
  function gallery(p, href) {
    const list = photos(p);
    const main = h("img", { src: list[0], alt: p.title, loading: "lazy", width: 400, height: 300 });
    const thumbs = list.length > 1 ? h("div", { class: "thumbs" }, list.map((src, n) => h("button", { type: "button", class: "thumb", "aria-label": `Photo ${n + 1} of ${list.length} of ${p.title}`, onclick: () => { main.src = src; } }, h("img", { src, alt: "", width: 40, height: 30 })))) : null;
    return h("div", { class: "tile photo" }, href ? h("a", { class: "imglink", href, "aria-label": `${p.title}: details` }, main) : main, thumbs);
  }
  const monogram = (t) => t.split(/\s+/).filter((w) => /^[A-Za-z]/.test(w)).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
  const plain = (html) => { const d = document.createElement("div"); d.innerHTML = html ?? ""; return d.textContent ?? ""; };
  function add(sku) {
    const line = cart.find((i) => i.sku === sku);
    if (line) line.quantity = Math.min(99, line.quantity + 1); else cart.push({ sku, quantity: 1 });
    saveCart();
    const l = $("#cartlink"); if (l) { l.classList.add("pulse"); setTimeout(() => l.classList.remove("pulse"), 300); }
  }

  // ---------------------------------------------------------------- checkout (Landfall's widget does the pricing and the PayPal button)
  let config = null;
  let widget = null;
  let widgetLoad = null;
  const money = (cur, v) => fmt(cur, v);

  function loadWidget() {
    if (window.Landfall) return Promise.resolve();
    if (widgetLoad) return widgetLoad;
    widgetLoad = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = config.landfallApi + "/api/widget/landfall.js";
      s.onload = resolve;
      s.onerror = () => { widgetLoad = null; reject(new Error("widget")); };
      document.head.appendChild(s);
    });
    return widgetLoad;
  }

  function receiptView(r) {
    return h("div", { class: "receipt", role: "status" },
      h("h2", {}, Number(r.tax_total) > 0 ? "Order paid. Nothing to pay at the door." : "Order paid."),
      h("dl", { class: "sum" },
        h("dt", {}, "Total charged"), h("dd", {}, `${money(r.currency, r.total)} ${r.currency}`),
        Number(r.tax_total) > 0 ? [h("dt", { class: "duty" }, "Import duties and taxes, included"), h("dd", { class: "duty" }, money(r.currency, r.tax_total))]
          : [h("dt", {}, "Import duties and taxes"), h("dd", {}, "none added")],
        h("dt", {}, "PayPal capture"), h("dd", { class: "mono" }, r.capture_id)),
      h("ul", { class: "rows" }, (r.items ?? []).map((i) => h("li", {}, h("span", {}, `${i.name} × ${i.quantity}`), h("span", {}, i.tax != null ? `duty ${money(r.currency, i.tax)}` : "")))),
      h("p", { class: "muted" }, "Kiln's server checked this order against Landfall's signed quote before it captured the payment."),
      h("p", {}, h("a", { href: "/" }, "Back to the shop")));
  }

  function renderLines() {
    const lines = $("#lines");
    if (!cart.length) { lines.replaceChildren(h("p", {}, "Your cart is empty. ", h("a", { href: "/" }, "Back to the shop"))); return; }
    lines.replaceChildren(h("ul", { class: "rows" }, cart.map((i) => {
      const f = bySku(i.sku);
      return h("li", {}, h("span", {}, f?.p.title ?? i.sku), h("span", { class: "qty" },
        h("button", { type: "button", "aria-label": `One fewer ${f?.p.title}`, onclick: () => change(i.sku, -1) }, "−"), ` ${i.quantity} `,
        h("button", { type: "button", "aria-label": `One more ${f?.p.title}`, onclick: () => change(i.sku, 1) }, "+")));
    })));
  }

  async function renderCheckout() {
    const box = $("#landfall");
    if (!box) return;
    renderLines();
    renderCalls();
    if (!cart.length) { widget = null; box.replaceChildren(); return; }
    if (widget) { widget.refresh(); return; }
    box.replaceChildren(h("p", { class: "muted" }, "Asking Landfall for the duty…"));
    try {
      if (!config) config = (await jget("/api/config")).json;
      if (!config?.publishableKey || !config?.paypalClientId) throw new Error("config");
      await loadWidget();
    } catch {
      box.replaceChildren(h("div", { class: "note warn" }, "Checkout is not available right now. Landfall or PayPal could not be reached. Nothing was charged."));
      return;
    }
    if (widget || !cart.length) return;
    widget = window.Landfall.mount({
      container: "#landfall",
      publishableKey: config.publishableKey,
      paypalClientId: config.paypalClientId,
      getCart: () => ({ items: cart.map((i) => ({ sku: i.sku, quantity: i.quantity })), shipTo: country().country }),
      validateUrl: "/api/validate",
      onExchange: (x) => { if (x.path === "/api/quote") calls.addQuote(x); else calls.add(x); renderCalls(); },
      onPaid: (j) => {
        cart = []; saveCart(); widget = null; calls.clear();
        $("#landfall").replaceChildren();
        $("#lines").replaceChildren();  // the receipt replaces the cart: no "your cart is empty" beside "order paid"
        $("#receipt").replaceChildren(receiptView(j.receipt));
        (j.exchanges ?? []).forEach((x) => calls.add(x));
        renderCalls();
      },
    });
  }
  function change(sku, d) {
    const l = cart.find((i) => i.sku === sku);
    if (!l) return;
    l.quantity += d;
    if (l.quantity < 1) cart = cart.filter((i) => i.sku !== sku);
    saveCart(); renderCheckout();
  }

  // ---------------------------------------------------------------- start
  async function start() {
    const [c, f, k, cfg] = await Promise.all([jget("/api/countries"), jget("/products.json"), jget("/api/known"), jget("/api/config")]);
    config = cfg.json;
    const cl = $("#coverage-link"); if (cl && config?.consoleUrl) cl.href = config.consoleUrl + "/coverage";
    countries = c.json ?? []; feed = f.json?.products ?? [];
    knownOk = k.status === 200;
    known = Object.fromEntries((k.json?.products ?? []).map((p) => [p.sku, p]));
    const sel = $("#shipto");
    if (sel) {
      sel.replaceChildren(...countries.map((x) => h("option", { value: x.country }, `${x.name ?? x.label ?? x.country} (${x.currency})`)));
      if (!countries.some((x) => x.country === ship)) ship = countries[0]?.country ?? "US";
      sel.value = ship;
      sel.addEventListener("change", () => { ship = sel.value; store.set("kiln_ship", ship); renderShop(); renderProduct(); renderCheckout(); });
    }
    // A product Landfall has not read yet cannot be priced: it leaves the cart with a plain note, instead of stopping the whole checkout.
    if (knownOk) {
      const gone = cart.filter((i) => !known[i.sku]);
      if (gone.length) {
        cart = cart.filter((i) => known[i.sku]);
        const names = gone.map((i) => bySku(i.sku)?.p.title ?? i.sku).join(", ");
        const host = $("#co") ?? $("#shop-lead");  // right under the page's own heading, inside its column
        if (host) host.after(h("div", { class: "note warn", id: "cart-note", role: "status" }, `${names} ${gone.length === 1 ? "is" : "are"} not available to order yet, so ${gone.length === 1 ? "it was" : "they were"} taken out of your cart.`));
      }
    }
    const lead = $("#shop-lead");
    if (lead) {
      const n = feed.filter((p) => standing(p.variants[0].sku) === "priced").length;
      const orderable = feed.filter((p) => standing(p.variants[0].sku) !== "unsynced").length;
      lead.textContent = !knownOk ? "Landfall could not be reached, so duty cannot be shown right now."
        : n ? "Products marked Duties included show the import duty and taxes in the price at checkout, for the country you pick: nothing to pay at the door. Anything else is sold without duty included, and your carrier may bill you on delivery."
        : orderable ? "Import duty is not included in these prices yet: your carrier may bill you on delivery."
        : "This shop is still being set up: nothing can be ordered until its products have been read by Landfall.";
    }
    saveCart(); renderShop(); renderProduct(); renderCheckout();
  }
  start();
})();
