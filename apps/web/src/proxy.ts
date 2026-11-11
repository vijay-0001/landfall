import { NextRequest, NextResponse } from "next/server";
import { COOKIE, gateDecision } from "@/lib/gate";

/** The password gate (see lib/gate.ts). A page without the cookie goes to /gate; an API call without it gets a plain 401. */
export function proxy(req: NextRequest) {
  const d = gateDecision({
    password: process.env.SITE_PASSWORD,
    path: req.nextUrl.pathname,
    host: req.headers.get("host") ?? undefined,
    publicUrl: process.env.PUBLIC_URL,
    cookie: req.cookies.get(COOKIE)?.value,
  });
  if (d === "allow") return NextResponse.next();
  if (d === "deny") return NextResponse.json({ detail: "This site needs a password. Open the site in your browser and enter it first." }, { status: 401 });
  const url = req.nextUrl.clone();
  url.pathname = "/gate";
  url.search = `?next=${encodeURIComponent(req.nextUrl.pathname + req.nextUrl.search)}`;
  return NextResponse.redirect(url);
}

export const config = { matcher: ["/((?!_next/static|_next/image).*)"] };
