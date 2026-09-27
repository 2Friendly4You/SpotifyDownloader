export type SpotifyResource = "playlist" | "track" | "album" | "artist";

export function spotifyResource(query: string): SpotifyResource | null {
  let url: URL;
  try {
    url = new URL(query);
  } catch {
    return null;
  }

  const host = url.hostname.toLowerCase();
  if (host !== "open.spotify.com" && host !== "www.open.spotify.com") {
    return null;
  }

  const parts = url.pathname.split("/").filter(Boolean);
  const head = parts[0]?.toLowerCase() ?? "";
  const resource = head.startsWith("intl-") ? parts[1]?.toLowerCase() : head;
  if (resource === "playlist" || resource === "track" || resource === "album" || resource === "artist") {
    return resource;
  }
  return null;
}
