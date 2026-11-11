"use client";
import Link from "next/link";
import { useState, useSyncExternalStore } from "react";
import { ErrorBox, LoadingBlock } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useAsync } from "@/lib/hooks";
import { KEY_EVENT, getKey } from "@/lib/merchant";

const box = { padding: 12, background: "var(--paper, #f4f1ea)", borderRadius: 8, overflowWrap: "anywhere" as const, whiteSpace: "pre-wrap" as const, margin: 0 };

function useStoredKey(): string | null {
  return useSyncExternalStore(
    (cb) => { window.addEventListener(KEY_EVENT, cb); window.addEventListener("storage", cb); return () => { window.removeEventListener(KEY_EVENT, cb); window.removeEventListener("storage", cb); }; },
    () => getKey(),
    () => null,
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return <button type="button" className="btn btn-ghost btn-sm" onClick={() => { navigator.clipboard?.writeText(text).then(() => setDone(true)).catch(() => undefined); }}>{done ? "Copied" : label}</button>;
}

export default function Keys() {
  const secret = useStoredKey();
  const me = useAsync(() => (secret ? api.getMe() : Promise.resolve(null)), `keys-${secret ?? "none"}`);
  const [show, setShow] = useState(false);
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const intro = (
    <>
      <div className="page-head"><div><h1>API keys</h1>
        <p>Landfall&apos;s console and your product feed need no key. These two keys connect the <b>script in your merchant portal</b> to Landfall: the widget on your checkout page, and your own server.</p></div></div>
    </>
  );
  if (!secret) {
    return (
      <>
        {intro}
        <div className="card pad-lg stack" style={{ maxWidth: 760 }}>
          <b>The built-in demo shop has no keys of its own.</b>
          <span className="muted">Keys belong to a store you connect. <Link href="/connect">Connect your store</Link> and its two keys appear here.</span>
        </div>
      </>
    );
  }
  if (me.error) return <>{intro}<ErrorBox error={me.error} onRetry={me.reload} /></>;
  if (!me.data) return <>{intro}<LoadingBlock label="Loading your keys" /></>;
  const pub = me.data.publishable_key ?? "";
  return (
    <>
      {intro}
      <div className="stack" style={{ gap: 20, maxWidth: 860 }}>
        <section className="card pad-lg stack" style={{ gap: 10 }} aria-label="Publishable key">
          <h2 style={{ margin: 0 }}>1. Publishable key: for your checkout page</h2>
          <p style={{ margin: 0 }}>Put it in the page where buyers pay. The widget uses it to ask Landfall for the duty on a cart. It can do nothing else, so it is safe to show in a web page.</p>
          <code className="mono" id="publishable-key" style={box}>{pub}</code>
          <div className="row"><CopyButton text={pub} label="Copy publishable key" /></div>
          <pre className="mono" style={box}>{`<script src="${origin}/api/widget/landfall.js"></script>\nLandfall.mount({ container: "#landfall", publishableKey: "${pub}", paypalClientId: "<your PayPal client id>", getCart, validateUrl: "/api/validate" })`}</pre>
        </section>
        <section className="card pad-lg stack" style={{ gap: 10 }} aria-label="Secret key">
          <h2 style={{ margin: 0 }}>2. Secret key: for your server only</h2>
          <p style={{ margin: 0 }}>After the buyer approves in PayPal and before your server captures the payment, it sends the PayPal order and the quote token to Landfall with this key. Landfall confirms the order carries the quoted duty. Landfall never holds your PayPal credentials. Never put this key in a web page.</p>
          <code className="mono" id="secret-key" style={box}>{show ? secret : `${secret.slice(0, 12)}${"•".repeat(24)}`}</code>
          <div className="row">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShow((v) => !v)}>{show ? "Hide secret key" : "Show secret key"}</button>
            <CopyButton text={secret} label="Copy secret key" />
          </div>
          <pre className="mono" style={box}>{`POST ${origin}/api/quotes/verify\nAuthorization: Bearer lf_test_…   (the secret key)\n{ "quote_token": "…", "paypal_order": { …as PayPal returned it… } }`}</pre>
          <small>This browser holds the key you signed in with. Landfall itself keeps only a fingerprint, so it cannot show the key again: if this browser&apos;s data is cleared, open a new account.</small>
        </section>
        <section className="card pad-lg stack" style={{ gap: 6 }} aria-label="The demo store">
          <h2 style={{ margin: 0 }}>For the demo store, Kiln &amp; Co.</h2>
          <p style={{ margin: 0 }}>Kiln is the merchant portal here. In its <b>Shop admin</b> (<span className="mono">/admin</span>, after staff login), open <b>Landfall connection</b> and paste the secret key. Kiln works out the publishable key, checks the secret with Landfall and keeps it on its server; then Kiln&apos;s checkout asks your account for duties.</p>
        </section>
      </div>
    </>
  );
}
