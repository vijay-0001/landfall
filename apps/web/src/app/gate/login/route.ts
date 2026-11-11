import { NextRequest, NextResponse } from "next/server";
import { COOKIE, passwordMatches, tokenFor } from "@/lib/gate";

/** Checks the password and sets the gate cookie (HttpOnly, 12 hours). The redirect only ever goes to a path on this site. */
export async function POST(req: NextRequest) {
  const password = process.env.SITE_PASSWORD;
  const form = await req.formData();
  const given = String(form.get("password") ?? "");
  const next = String(form.get("next") ?? "/");
  const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/";
  const base = process.env.NEXT_PUBLIC_SITE_URL ?? req.nextUrl.origin;
  if (!password || !passwordMatches(given, password)) {
    return NextResponse.redirect(new URL(`/gate?wrong=1&next=${encodeURIComponent(safeNext)}`, base), 303);
  }
  const res = NextResponse.redirect(new URL(safeNext, base), 303);
  res.cookies.set(COOKIE, tokenFor(password), {
    httpOnly: true, sameSite: "lax", secure: req.headers.get("x-forwarded-proto") === "https", path: "/", maxAge: 60 * 60 * 12,
  });
  return res;
}
