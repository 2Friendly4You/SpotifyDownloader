import { useTranslation } from "react-i18next";
import styles from "./RequestComponent.module.css";
import type { FailedTrack } from "./Types";

// The expandable list of songs that could not be saved, shared by the
// download card and the admin job list.
export default function FailedTrackList({ tracks }: { tracks: FailedTrack[] }) {
  const { t } = useTranslation();
  if (!tracks.length) {
    return null;
  }
  return (
    <details className={styles.failedTracks}>
      <summary>{t("RequestComponent.failedTracks.summary", { count: tracks.length })}</summary>
      <ul>
        {tracks.map((track, index) => (
          <li key={`${track.url ?? track.title}-${index}`}>
            <div className={styles.failedRow}>
              {track.url ? (
                <a href={track.url} target="_blank" rel="noopener noreferrer" className={styles.failedTitle}>
                  {track.title}
                </a>
              ) : (
                <span className={styles.failedTitle}>{track.title}</span>
              )}
              <span className={styles.failedReason}>
                {t(`RequestComponent.failedTracks.reasons.${track.reason}`, {
                  defaultValue: t("RequestComponent.failedTracks.reasons.download_failed"),
                })}
              </span>
            </div>
            {track.error && <span className={styles.failedError}>{track.error}</span>}
          </li>
        ))}
      </ul>
    </details>
  );
}
