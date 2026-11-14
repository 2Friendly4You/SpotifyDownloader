import type { DownloadRequest } from "./components/Types";

// What a user calls a download: the playlist, album or song name once the
// server knows it, before that the link or search text they entered.
export function requestName(request: Pick<DownloadRequest, "title" | "searchQuery">): string {
  return request.title || request.searchQuery;
}

// Finished downloads count as duplicates for this long; after that the
// zip may already be cleaned up and a new download is the normal case.
export const RECENT_DUPLICATE_MS = 24 * 60 * 60 * 1000;

const YOUTUBE_HOSTS = new Set(["youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"]);

// A comparison key for "is this the same download?". Spotify links differ
// in ?si= tracking parameters, intl-xx prefixes and trailing slashes but
// point at the same thing. Spotify ids are case-sensitive, so the path is
// kept as is.
export function normalizeQuery(query: string): string {
  const trimmed = query.trim();
  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    return `text:${trimmed.toLowerCase().replace(/\s+/g, " ")}`;
  }
  const host = url.hostname.toLowerCase().replace(/^www\./, "");
  const parts = url.pathname.split("/").filter(Boolean);
  if (host === "open.spotify.com") {
    if (parts[0]?.toLowerCase().startsWith("intl-")) {
      parts.shift();
    }
    return `spotify:${parts.map((part, index) => (index === 0 ? part.toLowerCase() : part)).join("/")}`;
  }
  if (YOUTUBE_HOSTS.has(host)) {
    const video = host === "youtu.be" ? parts[0] ?? "" : url.searchParams.get("v") ?? "";
    const list = url.searchParams.get("list") ?? "";
    return `youtube:${video}:${list}:${video || list ? "" : parts.join("/")}`;
  }
  return `url:${host}/${parts.join("/")}`;
}

export function findDuplicate(
  requests: DownloadRequest[],
  query: string,
  now: number = Date.now()
): DownloadRequest | undefined {
  const key = normalizeQuery(query);
  const matches = requests.filter((item) => normalizeQuery(item.searchQuery) === key);
  return (
    matches.find((item) => item.status === "pending" || item.status === "queued") ??
    matches.find(
      (item) => item.status === "completed" && now - new Date(item.timestamp).getTime() < RECENT_DUPLICATE_MS
    )
  );
}
