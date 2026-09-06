import { test } from "node:test";
import assert from "node:assert/strict";
import { request, clearPublicCache } from "../src/api.js";
import { roundTitle } from "../src/round.js";
const store = new Map();
globalThis.sessionStorage = {
  getItem: (k) => store.get(k),
  setItem: (k, v) => store.set(k, v),
  removeItem: (k) => store.delete(k),
};
test("round names never expose internal playoff sort numbers", () => {
  assert.deepEqual(roundTitle({ label: "Final", number: 9300 }), {
    title: "Finale",
    caption: "FAZA",
  });
  assert.equal(roundTitle({ label: "Round 7", number: 7 }).title, "7");
  assert.equal(roundTitle({ label: "7. kolo", number: 7 }).caption, "KOLO");
});
test("public cache reuses results and isolates filters; private requests bypass cache", async () => {
  clearPublicCache();
  let n = 0;
  globalThis.fetch = async () => new Response(JSON.stringify({ n: ++n }));
  assert.deepEqual(await request("/players/catalog?q=a", { cacheMs: 30000 }), {
    n: 1,
  });
  assert.deepEqual(await request("/players/catalog?q=a", { cacheMs: 30000 }), {
    n: 1,
  });
  assert.deepEqual(await request("/players/catalog?q=b", { cacheMs: 30000 }), {
    n: 2,
  });
  await request("/teams/me", { token: "user", cacheMs: 30000 });
  await request("/teams/me", { token: "user", cacheMs: 30000 });
  assert.equal(n, 4);
});
test("uncertain transfer retry reuses key; successful next operation uses new key", async () => {
  const keys = [];
  let n = 0;
  globalThis.fetch = async (url, options) => {
    keys.push(options.headers["Idempotency-Key"]);
    if (++n === 1) throw new TypeError("network");
    return new Response("{}");
  };
  const opts = { method: "POST", token: "a", body: { drop: "1", add: "2" } };
  await assert.rejects(request("/teams/1/transfers", opts));
  await request("/teams/1/transfers", opts);
  await request("/teams/1/transfers", opts);
  assert.equal(keys[0], keys[1]);
  assert.notEqual(keys[1], keys[2]);
});
test("parallel identical writes share one request; accounts have different keys", async () => {
  let n = 0;
  const keys = [];
  globalThis.fetch = async (url, options) => {
    ++n;
    keys.push(options.headers["Idempotency-Key"]);
    await new Promise((r) => setTimeout(r, 20));
    return new Response("{}");
  };
  const opts = { method: "POST", token: "a", body: { name: "one" } };
  await Promise.all([request("/teams", opts), request("/teams", opts)]);
  assert.equal(n, 1);
  await request("/teams", { ...opts, token: "b" });
  assert.notEqual(keys[0], keys[1]);
});
