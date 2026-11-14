// Run with `pnpm test` (Node's built-in runner; Node strips the TypeScript types).
import assert from "node:assert/strict";
import { test } from "node:test";
import { findDuplicate, normalizeQuery, requestName } from "../src/requestName.ts";

const PLAYLIST = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M";
const same = (a, b) => normalizeQuery(a) === normalizeQuery(b);

test("Spotify links match without tracking parameters, intl prefixes or trailing slashes", () => {
  assert.ok(same(`${PLAYLIST}?si=abc123`, PLAYLIST));
  assert.ok(same(PLAYLIST, "https://open.spotify.com/intl-de/playlist/37i9dQZF1DXcBWIGoYBM5M/?si=x&pt=1"));
  assert.ok(same(PLAYLIST, "https://OPEN.spotify.com/Playlist/37i9dQZF1DXcBWIGoYBM5M#top"));
});

test("Spotify ids are case-sensitive and the kind matters", () => {
  assert.ok(!same(PLAYLIST, "https://open.spotify.com/playlist/37i9dqzf1dxcbwigoybm5m"));
  assert.ok(!same(PLAYLIST, "https://open.spotify.com/album/37i9dQZF1DXcBWIGoYBM5M"));
});

test("YouTube links compare by video and playlist id", () => {
  assert.ok(same("https://www.youtube.com/watch?v=abc&t=10", "https://youtu.be/abc?si=x"));
  assert.ok(!same("https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abd"));
});

test("free-text searches ignore case and extra spaces", () => {
  assert.ok(same("  Daft   Punk ", "daft punk"));
});

const now = Date.parse("2026-11-14T12:00:00Z");
const request = (id, status, hoursAgo = 0, searchQuery = PLAYLIST) => ({
  unique_id: id,
  searchQuery,
  status,
  timestamp: new Date(now - hoursAgo * 3600 * 1000).toISOString(),
});

test("a running or queued copy wins over a finished one", () => {
  const list = [request("done", "completed", 1), request("running", "pending")];
  assert.equal(findDuplicate(list, `${PLAYLIST}?si=1`, now)?.unique_id, "running");
  assert.equal(findDuplicate([request("queued", "queued")], PLAYLIST, now)?.unique_id, "queued");
});

test("only recently finished downloads count, failed ones never", () => {
  assert.equal(findDuplicate([request("done", "completed", 2)], PLAYLIST, now)?.unique_id, "done");
  assert.equal(findDuplicate([request("old", "completed", 30)], PLAYLIST, now), undefined);
  assert.equal(findDuplicate([request("failed", "failed")], PLAYLIST, now), undefined);
});

test("cards are named after the title once it is known", () => {
  assert.equal(requestName({ searchQuery: PLAYLIST }), PLAYLIST);
  assert.equal(requestName({ searchQuery: PLAYLIST, title: "Today's Top Hits" }), "Today's Top Hits");
});
