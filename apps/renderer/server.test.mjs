import { test } from "node:test";
import assert from "node:assert/strict";
import { allowed, assertRenderable } from "./server.mjs";

test("only our own share pages can be rendered", () => {
  assert.ok(allowed("/share/time-machine?product=p_mug&origin=GB&destination=US"));
  assert.ok(allowed("/share/passport"));
  for (const bad of ["http://evil.example/", "//evil.example", "/products", "/share/../etc", "/share/a;rm", null, undefined]) assert.ok(!allowed(bad), String(bad));
});

test("an error page is never turned into an image", () => {
  assertRenderable(200);
  for (const bad of [404, 500, 502, undefined, 0]) assert.throws(() => assertRenderable(bad), /answered HTTP/);
});
