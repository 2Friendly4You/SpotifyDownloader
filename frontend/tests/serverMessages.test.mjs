import assert from "node:assert/strict";
import { test } from "node:test";
import { serverMessage } from "../src/serverMessages.ts";

test("known server messages are German for German users", () => {
  assert.equal(serverMessage("Search query is required", "de"), "Bitte gib einen Suchbegriff oder Link ein.");
  assert.equal(
    serverMessage("Download queue is full. Please try again later.", "de-DE"),
    "Die Warteschlange ist voll. Bitte versuch es später noch einmal."
  );
});

test("prefixed failures keep their detail", () => {
  assert.equal(
    serverMessage("Download failed: No songs found for that search.", "de"),
    "Download fehlgeschlagen: Für deine Suche wurden keine Songs gefunden."
  );
  assert.equal(serverMessage("Download failed: HTTP 403", "de"), "Download fehlgeschlagen: HTTP 403");
});

test("English and unknown messages stay as they are", () => {
  assert.equal(serverMessage("Download timed out.", "en"), "Download timed out.");
  assert.equal(serverMessage("Something odd", "de"), "Something odd");
  assert.equal(serverMessage("", "de"), "");
});
