"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { api } from "@/lib/api/client";
import { useAsync } from "@/lib/hooks";
import { KEY_EVENT, getKey, isDemo } from "@/lib/merchant";
import { LoadingBlock, Logo } from "./ui";

const LINKS = [
  { href: "/products", label: "Products" },
  { href: "/passport", label: "Passport" },
  { href: "/radar", label: "Rule Radar", badge: true },
  { href: "/connect", label: "Connect store" },
  { href: "/keys", label: "API keys" },
  { href: "/coverage", label: "Coverage and sources" },
];

export function SellerShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  // Is a store connected (or the demo shop chosen)? Read from this browser's storage without a state update inside an effect; "checking" on the server.
  const gate = useSyncExternalStore(
    (cb) => { window.addEventListener(KEY_EVENT, cb); window.addEventListener("storage", cb); return () => { window.removeEventListener(KEY_EVENT, cb); window.removeEventListener("storage", cb); }; },
    () => (getKey() || isDemo() ? "stored" : "none"),
    () => "checking",
  );
  const radar = useAsync(() => (getKey() || isDemo() ? api.getRadar() : Promise.resolve([])), `radar-nav-${path}`);
  const act = radar.data?.filter((a) => a.status === "act").length ?? 0;
  const [who, setWho] = useState(0);
  useEffect(() => { const f = () => setWho((n) => n + 1); window.addEventListener(KEY_EVENT, f); return () => window.removeEventListener(KEY_EVENT, f); }, []);
  // Nothing of any store is shown until one is connected (or the built-in demo shop is chosen on purpose): the Connect page is the way in.
  const open = path.startsWith("/connect") || path.startsWith("/coverage") || gate === "stored";
  useEffect(() => { if (gate === "none" && !open) router.replace("/connect?needs=store"); }, [gate, open, router]);
  const demo = gate === "stored" && !getKey() && isDemo();
  const shop = useAsync(() => (getKey() || isDemo() ? api.getCatalogue().then((c) => c.shop).catch(() => null) : Promise.resolve(null)), `shop-nav-${path}-${who}`);
  return (
    <div className="app">
      <a className="skip" href="#main">Skip to content</a>
      <nav className="nav" aria-label="Main">
        <Link className="brand" href="/"><Logo /> Landfall</Link>
        {LINKS.filter((l) => gate === "stored" || l.href === "/connect" || l.href === "/coverage").map((l) => (  // before a store is connected, only the pages that work are offered
          <Link key={l.href} href={l.href} className="link" aria-current={path.startsWith(l.href) ? "page" : undefined}>
            {l.label}{l.badge && act > 0 && <span className="count" aria-label={`${act} alerts`}>{act}</span>}
          </Link>
        ))}
        <Link className="pub" href="/time-machine">Public: Time Machine</Link>
        <div className="shopbox">{demo ? <b>Demo shop (sample data)</b> : <b>{shop.data?.name ?? (gate === "stored" && shop.loading ? "Loading…" : "No store connected")}</b>}<span>{demo ? "Not a real store. Connect yours on Connect store." : shop.data ? `${shop.data.city}, ${shop.data.country} · PayPal sandbox` : gate === "stored" && shop.loading ? "" : "Connect a store to begin"}</span></div>
      </nav>
      <main id="main" className="main">{open ? children : <LoadingBlock label="Checking your store" />}</main>
    </div>
  );
}
