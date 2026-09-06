import { test } from "node:test";
import assert from "node:assert/strict";
import { proxyHeaders } from "../proxy.mjs";
test("proxy replaces spoofed identity with direct peer and preserves auth", () => {
  const incoming = {
    "x-forwarded-for": "fake",
    forwarded: "for=fake",
    "x-real-ip": "fake",
    authorization: "Bearer test",
  };
  const out = proxyHeaders(incoming, "::ffff:192.0.2.2", "127.0.0.1:8001");
  assert.equal(out["x-forwarded-for"], "192.0.2.2");
  assert.equal(out.authorization, "Bearer test");
  assert.equal(out.forwarded, undefined);
  assert.equal(out["x-real-ip"], undefined);
  assert.equal(incoming["x-forwarded-for"], "fake");
  assert.notEqual(
    out["x-forwarded-for"],
    proxyHeaders(incoming, "192.0.2.3", "api")["x-forwarded-for"],
  );
});
