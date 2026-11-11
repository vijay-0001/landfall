// Kiln & Co. back office (mock). Text is always set with textContent, never as HTML.
(() => {
  const $ = (s) => document.querySelector(s);
  const CUR = ["GBP", "USD", "EUR", "AUD"];
  const h = (tag, attrs = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) { if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v); }
    for (const kid of kids.flat()) if (kid != null && kid !== false) e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return e;
  };
  let editing = null;      // the product being edited, or null when adding
  let keep = [];           // its existing photos still kept
  let chosen = [];         // files picked in this form
  const say = (text, bad) => { const m = $("#msg"); m.textContent = text || ""; m.className = "note" + (bad ? " warn" : ""); m.hidden = !text; };

  const toBase64 = (f) => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result)); r.onerror = no; r.readAsDataURL(f); });

  function renderPhotos() {
    const box = $("#photo-preview");
    box.replaceChildren(
      ...keep.map((src) => h("figure", { class: "ph" }, h("img", { src, alt: "Current photo", width: 96, height: 72 }),
        h("button", { type: "button", class: "mini", "aria-label": "Remove this photo", onclick: () => { keep = keep.filter((x) => x !== src); renderPhotos(); } }, "Remove"))),
      ...chosen.map((f, i) => h("figure", { class: "ph" }, h("img", { src: URL.createObjectURL(f), alt: `New photo ${i + 1}`, width: 96, height: 72 }),
        h("button", { type: "button", class: "mini", "aria-label": "Remove this new photo", onclick: () => { chosen = chosen.filter((_, j) => j !== i); renderPhotos(); } }, "Remove"))));
    $("#photo-count").textContent = `${keep.length + chosen.length} of 4 photos`;
  }

  function reset() {
    editing = null; keep = []; chosen = [];
    $("#pform").reset(); $("#sku").disabled = false;
    $("#form-title").textContent = "Add a product";
    $("#submit").textContent = "Add product"; $("#cancel").hidden = true;
    renderPhotos();
  }

  function edit(p) {
    editing = p.sku; keep = [...p.images]; chosen = [];
    $("#title").value = p.title; $("#description").value = p.description; $("#sku").value = p.sku; $("#sku").disabled = true;
    for (const c of CUR) $("#price-" + c).value = p.prices[c];
    $("#form-title").textContent = `Edit ${p.sku}`; $("#submit").textContent = "Save changes"; $("#cancel").hidden = false;
    renderPhotos(); say("");
    $("#pform").scrollIntoView({ block: "start" });
  }

  /** Products Landfall has not read yet are marked in the list, so the merchant knows to press Sync now in Landfall. */
  async function markUnsynced() {
    let k = null;
    try { const r = await fetch("/api/known"); if (!r.ok) return; k = await r.json(); } catch { return; }  // Landfall not answering: say nothing rather than guess
    const have = new Set((k?.products ?? []).map((p) => p.sku));
    let missing = 0;
    for (const li of document.querySelectorAll("#plist li.prow")) {
      const out = !have.has(li.dataset.sku);
      if (out) missing += 1;
      li.querySelector(".sync-flag")?.remove();
      if (out) li.querySelector(".pinfo").append(h("span", { class: "sync-flag muted" }, "Not in Landfall yet: press Sync now in Landfall. Shoppers cannot order it until then."));
    }
    const c = $("#count"); if (missing) c.textContent += `, ${missing} not in Landfall yet`;
  }

  async function list() {
    const r = await fetch("/api/admin/products");
    if (r.status === 401) { location.href = "/login"; return; }
    const j = await r.json();
    const ul = $("#plist");
    ul.replaceChildren(...j.products.map((p) => h("li", { class: "prow", "data-sku": p.sku },
      p.images[0] ? h("img", { src: p.images[0], alt: "", width: 64, height: 48 }) : h("div", { class: "noimg", "aria-hidden": "true" }, "no photo"),
      h("div", { class: "pinfo" }, h("b", {}, p.title), h("span", { class: "muted" }, `${p.sku} · ${p.images.length} photo${p.images.length === 1 ? "" : "s"} · $${p.prices.USD}`)),
      h("button", { type: "button", class: "mini", onclick: () => edit(p), "aria-label": `Edit ${p.title}` }, "Edit"),
      h("button", { type: "button", class: "mini danger", onclick: (ev) => askRemove(ev.currentTarget, p), "aria-label": `Remove ${p.title}` }, "Remove"))));
    $("#count").textContent = `${j.products.length} products`;
    markUnsynced();
  }

  function askRemove(btn, p) {
    const row = btn.closest("li");
    const bar = h("div", { class: "confirm", role: "group", "aria-label": `Remove ${p.title}?` }, h("span", {}, `Remove ${p.title} from the shop and the feed?`),
      h("button", { type: "button", class: "mini danger", onclick: async () => { const r = await fetch(`/api/admin/products/${p.sku}`, { method: "DELETE" }); say(r.ok ? `${p.title} was removed. Landfall stops selling it at its next sync.` : "That product could not be removed.", !r.ok); if (editing === p.sku) reset(); await list(); } }, "Yes, remove"),
      h("button", { type: "button", class: "mini", onclick: () => bar.remove() }, "Keep it"));
    row.append(bar);
  }

  $("#photos").addEventListener("change", (e) => {
    const picked = [...e.target.files];
    e.target.value = "";
    if (keep.length + chosen.length + picked.length > 4) { say("At most 4 photos per product.", true); return; }
    chosen = [...chosen, ...picked]; say(""); renderPhotos();
  });
  $("#cancel").addEventListener("click", () => { reset(); say(""); });

  $("#pform").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#submit"); btn.disabled = true; say("Saving…");
    try {
      const photos = await Promise.all(chosen.map(async (f) => ({ data: await toBase64(f) })));
      const body = { title: $("#title").value, description: $("#description").value, sku: $("#sku").value, prices: Object.fromEntries(CUR.map((c) => [c, $("#price-" + c).value])), photos, keep };
      const r = await fetch(editing ? `/api/admin/products/${editing}` : "/api/admin/products", { method: editing ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { say(j.detail ?? "That product could not be saved.", true); return; }
      say(`${j.product.title} is saved (${j.product.sku}, ${j.product.images.length} photo${j.product.images.length === 1 ? "" : "s"}). It is in the shop and in Kiln's product feed; Landfall picks it up at its next sync.`);
      reset(); await list();
    } catch { say("That product could not be saved.", true); } finally { btn.disabled = false; }
  });

  $("#logout").addEventListener("click", async () => { await fetch("/api/admin/logout", { method: "POST" }); location.href = "/login"; });
  // ---------------------------------------------------------------- Landfall connection (which Landfall account Kiln's checkout asks for duties)
  const cmsg = (text) => { const m = $("#conn-msg"); m.textContent = text || ""; m.hidden = !text; };
  async function showConnection() {
    const box = $("#conn-status");
    let j = null;
    try { j = await (await fetch("/api/admin/landfall")).json(); } catch { /* shown below */ }
    if (!j || j.detail) { box.textContent = "Could not read the connection."; box.className = "note warn"; return; }
    const a = j.account;
    box.className = "note" + (a ? "" : " warn");
    if (a) {
      const synced = a.last_synced_at ? `last synced ${new Date(a.last_synced_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" })} UTC` : "not synced yet";
      box.textContent = `Connected to the Landfall account "${a.name}" (${a.city}, ${a.country}): ${a.product_count} product${a.product_count === 1 ? "" : "s"}, ${synced}. ` +
        (j.source === "saved" ? `Kiln's checkout asks this account for duties, for the products it has synced and the seller has accepted.` : `This is the demo account from the server's settings; add your own keys below to use another account.`) + ` Publishable key in the checkout: ${j.publishable}.`;
    } else box.textContent = j.problem ?? "Not connected.";
    $("#conn-clear").hidden = j.source !== "saved";
  }
  $("#conn-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#conn-save"); btn.disabled = true; cmsg("");
    try {
      const r = await fetch("/api/admin/landfall", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ secret: $("#conn-secret").value, publishable: $("#conn-pub").value }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { cmsg(j.detail ?? "That could not be saved."); return; }
      $("#conn-secret").value = ""; $("#conn-pub").value = "";  // the secret is not kept in the page once it is saved
      await showConnection();
    } catch { cmsg("That could not be saved."); } finally { btn.disabled = false; }
  });
  $("#conn-clear").addEventListener("click", async () => { cmsg(""); await fetch("/api/admin/landfall", { method: "DELETE" }); await showConnection(); });

  reset(); list(); showConnection();
})();
