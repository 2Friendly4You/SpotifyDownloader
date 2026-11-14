// The server answers in English. German users get these known messages in
// German; anything unknown (for example a raw spotDL error) is shown as is.
const GERMAN: Record<string, string> = {
  "Search query is required": "Bitte gib einen Suchbegriff oder Link ein.",
  "Search query is too long": "Dein Suchbegriff ist zu lang.",
  "Invalid output format": "Dieses Ausgabeformat gibt es nicht.",
  "Invalid input provided": "Die Eingabe ist ungültig.",
  "Download queue is full. Please try again later.":
    "Die Warteschlange ist voll. Bitte versuch es später noch einmal.",
  "Request is not running or queued.": "Dieser Download läuft nicht mehr.",
  "Request not found or expired.": "Diesen Download gibt es nicht mehr oder er ist abgelaufen.",
  "File was marked completed but is now missing.": "Die Datei war fertig, ist aber nicht mehr da.",
  "Download timed out.": "Der Download hat zu lange gedauert und wurde abgebrochen.",
  "Archive file was not created.": "Die ZIP-Datei wurde nicht erstellt.",
  "The downloaded archive is corrupted.": "Die ZIP-Datei ist beschädigt.",
  "The downloaded archive is empty.": "Die ZIP-Datei ist leer.",
  "No songs found for that search.": "Für deine Suche wurden keine Songs gefunden.",
  "No files were downloaded.": "Es wurden keine Dateien heruntergeladen.",
};

const GERMAN_PREFIXES: [string, string][] = [
  ["Download failed: ", "Download fehlgeschlagen: "],
  ["YouTube download failed: ", "YouTube-Download fehlgeschlagen: "],
  ["An unexpected error occurred during spotdl processing: ", "Unerwarteter Fehler bei spotDL: "],
];

export function serverMessage(message: string, language: string | undefined): string {
  if (!message || !(language || "").toLowerCase().startsWith("de")) return message;
  if (GERMAN[message]) return GERMAN[message];
  for (const [prefix, german] of GERMAN_PREFIXES) {
    if (message.startsWith(prefix)) {
      const rest = message.slice(prefix.length);
      return german + (GERMAN[rest] ?? rest);
    }
  }
  return message;
}
