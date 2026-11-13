export type RoughEta = {
  key: "underMinute" | "minutes" | "hours";
  value: number;
};

// Turn seconds into a coarse value that is easy to plan with:
// under a minute, whole minutes up to 10, steps of 5 minutes up to an hour,
// then half hours. The backend estimate is rough, so the UI should be too.
export function roughEta(seconds?: number | null): RoughEta | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) {
    return null;
  }
  if (seconds < 60) {
    return { key: "underMinute", value: 0 };
  }
  const minutes = seconds / 60;
  if (minutes < 10) {
    return { key: "minutes", value: Math.ceil(minutes) };
  }
  if (minutes < 55) {
    return { key: "minutes", value: Math.ceil(minutes / 5) * 5 };
  }
  return { key: "hours", value: Math.max(1, Math.round(minutes / 30) / 2) };
}
