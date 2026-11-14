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

export type EtaLabel = RoughEta["key"] | "almostDone" | "calculating";

// Below this the countdown says "almost done" instead of a number, so a card
// whose estimate has run out while the last song converts never looks stuck.
export const ALMOST_DONE_SECONDS = 5;

export function etaLabel(secondsLeft: number | null, estimating: boolean): { key: EtaLabel; value: number } | null {
  if (secondsLeft != null && Number.isFinite(secondsLeft)) {
    if (secondsLeft <= ALMOST_DONE_SECONDS) {
      return { key: "almostDone", value: 0 };
    }
    return roughEta(secondsLeft);
  }
  return estimating ? { key: "calculating", value: 0 } : null;
}
