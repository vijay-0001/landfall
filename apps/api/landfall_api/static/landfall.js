/* Landfall checkout widget. One script on the merchant's checkout page.
 *
 *   <div id="landfall"></div>
 *   <script src="https://YOUR-LANDFALL/api/widget/landfall.js"></script>
 *   <script>
 *     Landfall.mount({
 *       container: "#landfall",
 *       publishableKey: "lf_pub_...",          // quote-only, safe in a web page
 *       paypalClientId: "YOUR_PUBLIC_PAYPAL_CLIENT_ID",
 *       getCart: () => ({ items: [{ sku: "MUG-001", quantity: 1 }], shipTo: "US" }),
 *       validateUrl: "/landfall/validate",     // YOUR server endpoint (see docs/merchant-journey.md)
 *     });
 *   </script>
 *
 * What it does: asks Landfall for the duty (no secret, no AI), shows the duty line and the total, renders the PayPal button through PayPal's own SDK with the
 * merchant's public client ID, and builds the PayPal order from Landfall's tax lines. After the buyer approves, no money has moved: the merchant's server checks the
 * order against Landfall's signed quote, and only then captures. Landfall never sees a PayPal credential. Call controller.refresh() when the cart or country changes.
 * Text is always set with textContent, never as HTML.
 */
(function () {
  "use strict";
  var SYM = { USD: "$", GBP: "£", EUR: "€", AUD: "A$", CAD: "C$" };
  var script = document.currentScript;

  function fmt(cur, amount) { return (SYM[cur] || cur + " ") + Number(amount).toFixed(2); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function css() {
    if (document.getElementById("lf-css")) return;
    var s = el("style");
    s.id = "lf-css";
    s.textContent = ".lf-summary{font:inherit;margin:0 0 12px}.lf-row{display:flex;justify-content:space-between;gap:12px;padding:4px 0}" +
      ".lf-duty{font-weight:600;color:#0b5c55}.lf-total{font-weight:700;font-size:1.2em;border-top:1px solid currentColor;margin-top:6px;padding-top:8px}" +
      ".lf-note{font-size:.9em;opacity:.8;margin:6px 0}.lf-msg{margin:10px 0;padding:10px 12px;border-radius:8px;border:1px solid #d6d0c4;font-size:.95em}" +
      ".lf-msg.lf-warn{border-color:#c2410c}.lf-msg:empty{display:none}";
    document.head.appendChild(s);
  }

  function mount(opts) {
    css();
    var root = typeof opts.container === "string" ? document.querySelector(opts.container) : opts.container;
    if (!root) throw new Error("Landfall: the container was not found");
    if (!opts.publishableKey || !opts.paypalClientId || !opts.getCart || !opts.validateUrl) throw new Error("Landfall: publishableKey, paypalClientId, getCart and validateUrl are required");
    var api = (opts.apiBase || (script && script.src ? new URL(script.src).origin : "")).replace(/\/$/, "");
    var summary = el("div", "lf-summary"), pay = el("div", "lf-pay"), msg = el("div", "lf-msg");
    root.replaceChildren(summary, pay, msg);
    var state = { quote: null, sent: null, sdkCurrency: null, buttonsFor: null };

    function say(text, warn) { msg.textContent = text || ""; msg.className = "lf-msg" + (warn ? " lf-warn" : ""); }
    function tell(x) { if (opts.onExchange) opts.onExchange(x); }

    function ask() {
      var cart = opts.getCart();
      if (!cart || !cart.items || !cart.items.length) return Promise.resolve({ status: 0, json: { detail: "The cart is empty" } });
      var body = { ship_to_country: cart.shipTo, items: cart.items };
      var t = Date.now();
      return fetch(api + "/api/quote", { method: "POST", headers: { "Content-Type": "application/json", "X-Landfall-Key": opts.publishableKey }, body: JSON.stringify(body) })
        .then(function (r) {
          return r.json().catch(function () { return null; }).then(function (j) {
            tell({ method: "POST", path: "/api/quote", auth: "X-Landfall-Key: " + opts.publishableKey.slice(0, 12) + "…", request: body, status: r.status, response: j, ms: Date.now() - t });
            return { status: r.status, json: j };
          });
        })
        .catch(function () { return { status: 0, json: { detail: "Landfall did not answer. Nothing was charged." } }; });
    }

    function niceDate(iso) { var d = new Date(iso + "T00:00:00Z"); return isNaN(d) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }); }

    function show(q) {
      summary.replaceChildren();
      function row(label, value, cls) { var r = el("div", "lf-row " + (cls || "")); r.appendChild(el("span", "", label)); r.appendChild(el("span", "", value)); summary.appendChild(r); }
      row("Items", fmt(q.currency, q.item_total.amount));
      row("Shipping", fmt(q.currency, q.shipping.amount));
      // Say only what was priced: an order with no priced item never claims "included".
      var priced = q.lines.filter(function (l) { return l.duties_included; }).length;
      if (!q.duties_included) row("Import duties and taxes", "Not added", "lf-nodty");
      else row(priced < q.lines.length ? "Import duties and taxes, included for the items priced (calculated by Landfall)" : "Import duties and taxes, included (calculated by Landfall)", fmt(q.currency, q.tax_total.amount), "lf-duty");
      row("Total", fmt(q.currency, q.total.amount) + " " + q.currency, "lf-total");
      if (q.duties_included) summary.appendChild(el("p", "lf-note", "Estimated from published rates for the expected import date, " + niceDate(q.rates_as_of) + ". Shown as tax on your PayPal receipt."));
      else summary.appendChild(el("p", "lf-note", "No duty is added to this order. Customs or the carrier may bill you on delivery."));
      q.lines.forEach(function (l) { if (!l.duties_included) summary.appendChild(el("p", "lf-note", l.title + ": " + l.unpriced_reason)); });
    }

    function loadSdk(currency) {
      if (state.sdkCurrency === currency && window.paypal) return Promise.resolve();
      return new Promise(function (resolve, reject) {
        var old = document.querySelector("script[data-landfall-paypal]");
        if (old) old.remove();
        try { delete window.paypal; } catch (e) { window.paypal = undefined; }
        var s = document.createElement("script");
        s.src = "https://www.paypal.com/sdk/js?client-id=" + encodeURIComponent(opts.paypalClientId) + "&currency=" + encodeURIComponent(currency) + "&intent=capture&commit=true";
        s.setAttribute("data-landfall-paypal", "1");
        s.onload = function () { state.sdkCurrency = currency; state.buttonsFor = null; resolve(); };
        s.onerror = function () { reject(new Error("PayPal did not load")); };
        document.head.appendChild(s);
      });
    }

    function validate(orderId) {
      var token = state.sent && state.sent.quote_token;
      return fetch(opts.validateUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ order_id: orderId, quote_token: token }) })
        .then(function (r) { return r.json().catch(function () { return {}; }); })
        .then(function (j) {
          (j.exchanges || []).forEach(tell);
          if (j.status === "captured") { say("Order paid. Nothing to pay at the door."); if (opts.onPaid) opts.onPaid(j); }
          else if (j.status === "changed") { say("The price changed while you were paying. Nothing was charged. Please review the new total.", true); if (opts.onChanged) opts.onChanged(j); refresh(); }
          else say(j.message || "We could not complete the payment. Nothing was charged.", true);
        })
        .catch(function () { say("We could not complete the payment. Nothing was charged.", true); });
    }

    function buttons(currency) {
      if (state.buttonsFor === currency) return;
      pay.replaceChildren();
      state.buttonsFor = currency;
      window.paypal.Buttons({
        // a fresh quote at click time: the buyer always pays what Landfall has just calculated
        createOrder: function (data, actions) {
          return ask().then(function (r) {
            if (r.status !== 200 || !r.json) { say((r.json && r.json.detail) || "This order cannot be priced.", true); throw new Error("quote failed"); }
            state.sent = r.json;
            show(r.json);
            return actions.order.create({ intent: "CAPTURE", purchase_units: [r.json.paypal_purchase_unit] });
          });
        },
        onApprove: function (data) { say("Checking your order…"); return validate(data.orderID); },
        onCancel: function () { say("You cancelled the payment at PayPal. Nothing was charged and your cart is still here."); },
        onError: function () { say("PayPal could not start the payment. Nothing was charged.", true); },
      }).render(pay);
    }

    var seq = 0;
    function refresh() {
      say("");
      var mine = ++seq;
      return ask().then(function (r) {
        if (mine !== seq) return;  // a newer cart or country was asked about meanwhile: never show an out-of-date quote
        if (r.status !== 200 || !r.json) {
          state.quote = null;
          summary.replaceChildren();
          pay.replaceChildren();
          state.buttonsFor = null;
          say((r.json && r.json.detail) || "This order cannot be priced.", true);
          return;
        }
        state.quote = r.json;
        show(r.json);
        if (opts.onQuote) opts.onQuote(r.json);
        return loadSdk(r.json.currency).then(function () { buttons(r.json.currency); }).catch(function () { say("PayPal did not load. Nothing was charged.", true); });
      });
    }

    refresh();
    return { refresh: refresh };
  }

  window.Landfall = { mount: mount };
})();
