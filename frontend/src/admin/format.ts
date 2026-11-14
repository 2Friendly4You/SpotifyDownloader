// Formatting and grouping for the admin page. Plain functions so they can be
// unit tested without a browser.

export function formatBytes(bytes: number | null | undefined, locale: string): string {
  if (bytes == null || !Number.isFinite(bytes)) {
    return "–";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${value.toLocaleString(locale, { maximumFractionDigits: digits, minimumFractionDigits: 0 })} ${units[unit]}`;
}

// "42 s", "3 min 05 s", "1 h 12 min", "3 d 4 h": coarse and short.
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) {
    return "–";
  }
  const s = Math.round(seconds);
  if (s < 60) {
    return `${s} s`;
  }
  const minutes = Math.floor(s / 60);
  if (minutes < 60) {
    return `${minutes} min ${String(s % 60).padStart(2, "0")} s`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    return `${hours} h ${String(minutes % 60).padStart(2, "0")} min`;
  }
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

const RELATIVE_STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["second", 60],
  ["minute", 60],
  ["hour", 24],
  ["day", 30],
  ["month", 12],
  ["year", Infinity],
];

export function formatRelative(epochSeconds: number | null | undefined, locale: string, now = Date.now()): string {
  if (!epochSeconds) {
    return "–";
  }
  let delta = epochSeconds - now / 1000;
  const format = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  for (const [unit, size] of RELATIVE_STEPS) {
    if (Math.abs(delta) < size) {
      return format.format(Math.round(delta), unit);
    }
    delta /= size;
  }
  return format.format(Math.round(delta), "year");
}

export function formatDateTime(epochSeconds: number | null | undefined, locale: string): string {
  if (!epochSeconds) {
    return "–";
  }
  return new Date(epochSeconds * 1000).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

export type DayBucket = { key: string; date: Date; completed: number; failed: number; cancelled: number };

function dayKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

// Finished jobs per local calendar day, oldest first, including empty days.
export function groupByDay(finishes: [number, string][], days: number, now = new Date()): DayBucket[] {
  const buckets: DayBucket[] = [];
  const index = new Map<string, DayBucket>();
  for (let offset = days - 1; offset >= 0; offset -= 1) {
    const date = new Date(now.getFullYear(), now.getMonth(), now.getDate() - offset);
    const bucket = { key: dayKey(date), date, completed: 0, failed: 0, cancelled: 0 };
    buckets.push(bucket);
    index.set(bucket.key, bucket);
  }
  for (const [finishedAt, status] of finishes) {
    const bucket = index.get(dayKey(new Date(finishedAt * 1000)));
    if (bucket && (status === "completed" || status === "failed" || status === "cancelled")) {
      bucket[status] += 1;
    }
  }
  return buckets;
}
