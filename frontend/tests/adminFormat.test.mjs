import assert from "node:assert/strict";
import { test } from "node:test";
import { formatBytes, formatDuration, groupByDay } from "../src/admin/format.ts";

test("bytes are shown in the largest sensible unit", () => {
  assert.equal(formatBytes(512, "en"), "512 B");
  assert.equal(formatBytes(1536, "en"), "1.5 KB");
  assert.equal(formatBytes(918.02 * 1024 * 1024, "de"), "918 MB");
  assert.equal(formatBytes(null, "en"), "–");
});

test("durations stay short", () => {
  assert.equal(formatDuration(42), "42 s");
  assert.equal(formatDuration(185), "3 min 05 s");
  assert.equal(formatDuration(3 * 3600 + 120), "3 h 02 min");
  assert.equal(formatDuration(-1), "–");
});

test("finished jobs are grouped by local day with empty days kept", () => {
  const now = new Date(2026, 10, 14, 12, 0);
  const at = (day, hour) => new Date(2026, 10, day, hour).getTime() / 1000;
  const days = groupByDay([[at(14, 1), "completed"], [at(14, 9), "failed"], [at(12, 23), "completed"], [at(1, 1), "completed"]], 3, now);
  assert.deepEqual(days.map((d) => [d.key, d.completed, d.failed]), [
    ["2026-11-12", 1, 0],
    ["2026-11-13", 0, 0],
    ["2026-11-14", 1, 1],
  ]);
});
