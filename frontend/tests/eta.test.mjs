import assert from "node:assert/strict";
import { test } from "node:test";
import { etaLabel, roughEta } from "../src/eta.ts";

test("no estimate yet says calculating only while the job can be estimated", () => {
  assert.deepEqual(etaLabel(null, true), { key: "calculating", value: 0 });
  assert.equal(etaLabel(null, false), null);
});

test("a countdown that runs out says almost done instead of standing still", () => {
  assert.equal(etaLabel(0, true).key, "almostDone");
  assert.equal(etaLabel(4, true).key, "almostDone");
  assert.equal(etaLabel(30, true).key, "underMinute");
});

test("longer estimates stay coarse", () => {
  assert.deepEqual(etaLabel(125, true), { key: "minutes", value: 3 });
  assert.deepEqual(roughEta(40 * 60), { key: "minutes", value: 40 });
});
