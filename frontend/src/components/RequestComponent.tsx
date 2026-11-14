import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import styles from "./RequestComponent.module.css";
import type { DownloadRequest } from "./Types";
import { useDownloads } from "../DownloadsContext";
import { etaLabel as pickEtaLabel } from "../eta";
import { requestName } from "../requestName";
import { serverMessage } from "../serverMessages";

const ETA_TICK_MS = 5000;

// Re-render every few seconds while active, so the time left counts down
// between server updates instead of standing still.
function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) {
      return undefined;
    }
    const timer = window.setInterval(() => setNow(Date.now()), ETA_TICK_MS);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

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
  const now = useNow(request.status === "pending");
  const secondsLeft =
    request.etaSeconds == null
      ? null
      : Math.max(0, request.etaSeconds - (request.etaReceivedAt ? (now - request.etaReceivedAt) / 1000 : 0));
  // Before the server has measured anything it sends no estimate; say so
  // instead of guessing "under a minute".
  const estimating = request.status === "pending" && (searching || downloading || retrying);
  const eta = request.status === "pending" ? pickEtaLabel(secondsLeft, estimating) : null;
  const etaLabel = eta
    ? t(`RequestComponent.eta.${eta.key}`, { value: eta.value.toLocaleString(i18n.language) })
    : "";
  const secondaryLabel = [runningLabel, etaLabel].filter(Boolean).join(" · ");

  const failedTracks =
    request.status === "completed" || request.status === "failed" ? request.failedTracks ?? [] : [];

  // One control per card: while the job is queued or running the trash can
  // cancels it on the server and deletes its files, afterwards it only removes the card.
  const cancellable = request.status === "pending" || request.status === "queued";
  const closeLabel = t(cancellable ? "RequestComponent.cancelAndDelete" : "RequestComponent.remove");
  const showActions = request.status === "completed" || request.status === "failed";

  const name = requestName(request);
  const isLink = /^https?:\/\//i.test(request.searchQuery.trim());
  // The link stays visible under the name, so two playlists with the same
  // name can still be told apart.
  const sourceLine = request.title
    ? request.title !== request.searchQuery
      ? request.searchQuery
      : ""
    : isLink && cancellable
      ? t("RequestComponent.resolvingName")
      : "";

  return (
    <div className={`${styles.root} ${styles[request.status] || ""}`}>
      <div className={styles.header}>
        <div className={styles.titleBlock}>
          <h2 title={name}>{name}</h2>
          {sourceLine && (
            <p className={styles.source} title={request.title ? request.searchQuery : undefined}>
              {sourceLine}
            </p>
          )}
        </div>
        <button
          type="button"
          className={styles.closeButton}
          onClick={handleClose}
          aria-label={closeLabel}
          title={closeLabel}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3 6h18" />
            <path d="M8 6V4.5A1.5 1.5 0 0 1 9.5 3h5A1.5 1.5 0 0 1 16 4.5V6" />
            <path d="M5.5 6l1 13.5A1.5 1.5 0 0 0 8 21h8a1.5 1.5 0 0 0 1.5-1.5L18.5 6" />
            <path d="M10 10.5v6M14 10.5v6" />
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
      {request.message && <p className={styles.message}>{serverMessage(request.message, i18n.language)}</p>}
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
