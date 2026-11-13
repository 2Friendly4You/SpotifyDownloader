import { Trans, useTranslation } from "react-i18next";
import styles from "./RequestComponent.module.css";
import type { DownloadRequest } from "./Types";
import { useDownloads } from "../DownloadsContext";
import { roughEta } from "../eta";

function RequestComponent({
  request,
  handleClose,
}: {
  request: DownloadRequest;
  handleClose: () => void;
}) {
  const { startFileDownload, retryRequest } = useDownloads();
  const { t, i18n } = useTranslation();
  const progress = Math.max(0, Math.min(100, Math.round(request.progress ?? 0)));
  const progressLabel = request.progressMessage
    ? t(`RequestComponent.progress.${request.progressMessage}`, {
        defaultValue: request.progressMessage,
      })
    : "";

  const searching = request.progressMessage === "Searching";
  const retrying = request.progressMessage === "Retrying";
  const downloading = request.progressMessage === "Downloading";
  // spotDL works on several songs at once, so the card shows how many are
  // finished instead of whichever song reported its own step last.
  const showCount =
    (searching || retrying || (downloading && (request.songsTotal ?? 0) > 1)) && Boolean(request.songsTotal);
  const songCount = showCount
    ? t("RequestComponent.searchCount", { done: request.songsDone ?? 0, total: request.songsTotal })
    : "";
  const runningLabel =
    (downloading || retrying) && request.songsRunning && (request.songsTotal ?? 0) > 1
      ? t("RequestComponent.running", { count: request.songsRunning })
      : "";
  const stageLabel = songCount ? `${progressLabel} ${songCount}` : progressLabel;
  const eta = roughEta(request.etaSeconds);
  const etaLabel = eta
    ? t(`RequestComponent.eta.${eta.key}`, { value: eta.value.toLocaleString(i18n.language) })
    : "";
  const secondaryLabel = [runningLabel, etaLabel].filter(Boolean).join(" · ");

  const failedTracks =
    request.status === "completed" || request.status === "failed" ? request.failedTracks ?? [] : [];

  const showActions = request.status === "completed" || request.status === "failed";

  return (
    <div className={`${styles.root} ${styles[request.status] || ""}`}>
      <div className={styles.header}>
        <h2 title={request.searchQuery}>{request.searchQuery}</h2>
        <button type="button" className={styles.closeButton} onClick={handleClose} aria-label={t("RequestComponent.remove")}>
          <svg viewBox="0 0 12 12" aria-hidden="true">
            <path d="M2.5 2.5 L9.5 9.5 M9.5 2.5 L2.5 9.5" />
          </svg>
        </button>
      </div>
      <p className={styles.status}>
        <Trans i18nKey={`RequestComponent.status.${request.status}`}>{request.status}</Trans>
      </p>
      {request.status === "queued" && request.queuePosition != null && (
        <p className={styles.queuePosition}>
          {t("RequestComponent.queuePosition", { position: request.queuePosition })}
        </p>
      )}
      {request.status === "pending" && (
        <div className={styles.progressBlock}>
          <div className={styles.progressMeta}>
            <span className={styles.progressPercent}>{progress}%</span>
            {stageLabel && <span className={styles.progressStage}>{stageLabel}</span>}
          </div>
          <div
            className={`${styles.progressTrack} ${searching ? styles.progressSearching : ""}`}
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress}
            aria-valuetext={[`${progress}%`, stageLabel, secondaryLabel].filter(Boolean).join(", ")}
          >
            <div className={styles.progressFill} style={{ width: `${progress}%` }} />
          </div>
          {secondaryLabel && <span className={styles.progressEta}>{secondaryLabel}</span>}
        </div>
      )}
      {request.message && <p className={styles.message}>{request.message}</p>}
      {failedTracks.length > 0 && (
        <details className={styles.failedTracks}>
          <summary>{t("RequestComponent.failedTracks.summary", { count: failedTracks.length })}</summary>
          <ul>
            {failedTracks.map((track, index) => (
              <li key={`${track.url ?? track.title}-${index}`}>
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
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className={styles.timestamp}>{new Date(request.timestamp).toLocaleString()}</p>
      {showActions && (
        <div className={styles.buttonContainer}>
          {request.status === "completed" && request.url && (
            <button type="button" className={styles.downloadButton} onClick={() => startFileDownload(request)}>
              <Trans i18nKey="RequestComponent.download">Download</Trans>
            </button>
          )}
          {request.status === "failed" && request.url && (
            <button type="button" className={styles.downloadButton} onClick={() => startFileDownload(request)}>
              <Trans i18nKey="RequestComponent.errorLog">Error Log</Trans>
            </button>
          )}
          {request.status === "failed" && (
            <button type="button" className={styles.retryButton} onClick={() => retryRequest(request.unique_id)}>
              <Trans i18nKey="RequestComponent.retry">Retry</Trans>
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export { RequestComponent };
