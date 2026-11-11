import { describe, expect, it } from "vitest";
import { COOKIE, gateDecision, passwordMatches, tokenFor } from "./gate";

const base = { password: "s3cret-pass", host: "landfall.example.org", publicUrl: "https://landfall.example.org", cookie: undefined as string | undefined };

describe("the password gate", () => {
  it("is off when no password is set", () => {
    expect(gateDecision({ ...base, password: undefined, path: "/products" })).toBe("allow");
    expect(gateDecision({ ...base, password: "", path: "/api/products/p/recommend" })).toBe("allow");
  });
  it("does not gate traffic from inside the server network (the share-image renderer asks for web:3000)", () => {
    expect(gateDecision({ ...base, host: "web:3000", path: "/share/passport" })).toBe("allow");
    expect(gateDecision({ ...base, host: "127.0.0.1:3000", path: "/api/catalogue" })).toBe("allow");
  });
  it("gates the public host whatever the port or letter case, and fails closed if PUBLIC_URL is missing", () => {
    expect(gateDecision({ ...base, host: "LANDFALL.example.org:443", path: "/products" })).toBe("login");
    expect(gateDecision({ ...base, publicUrl: undefined, host: "web:3000", path: "/products" })).toBe("login");
  });
  it("sends a visitor without the cookie to the password page", () => {
    for (const p of ["/", "/products", "/products/p_mug", "/connect", "/keys", "/radar", "/passport", "/time-machine", "/ops", "/shop", "/checkout"]) {
      expect(gateDecision({ ...base, path: p }), p).toBe("login");
    }
  });
  it("answers an API call without the cookie with 401, never with data", () => {
    for (const p of ["/api/catalogue", "/api/products/p_mug/assistant", "/api/products/p_mug/recommend", "/api/ops/rules", "/api/merchants", "/api/passport"]) {
      expect(gateDecision({ ...base, path: p }), p).toBe("deny");
    }
  });
  it("leaves open exactly what a shop needs from a shopper's browser, and the public pages", () => {
    for (const p of ["/api/quote", "/api/widget/landfall.js", "/api/health", "/api/coverage", "/coverage", "/gate", "/gate/login", "/_next/static/x.js", "/favicon.ico"]) {
      expect(gateDecision({ ...base, path: p }), p).toBe("allow");
    }
  });
  it("does not open look-alike paths", () => {
    for (const p of ["/api/quotes/verify", "/api/quote/x", "/api/coverage-private", "/coverage-secret", "/gateway", "/api/widgetx"]) {
      expect(gateDecision({ ...base, path: p }), p).not.toBe("allow");
    }
  });
  it("lets a visitor with the right cookie through, and refuses a wrong or old one", () => {
    expect(gateDecision({ ...base, path: "/products", cookie: tokenFor("s3cret-pass") })).toBe("allow");
    expect(gateDecision({ ...base, path: "/api/catalogue", cookie: tokenFor("s3cret-pass") })).toBe("allow");
    expect(gateDecision({ ...base, path: "/products", cookie: tokenFor("other") })).toBe("login");
    expect(gateDecision({ ...base, path: "/products", cookie: "s3cret-pass" })).toBe("login");  // the password itself is not the cookie
  });
  it("compares passwords without leaking length or position", () => {
    expect(passwordMatches("s3cret-pass", "s3cret-pass")).toBe(true);
    expect(passwordMatches("s3cret-pas", "s3cret-pass")).toBe(false);
    expect(passwordMatches("", "s3cret-pass")).toBe(false);
    expect(COOKIE).toBe("lf_gate");
  });
});
