import { Trans, useTranslation } from "react-i18next";
import styles from "./RequestComponent.module.css";
import type { DownloadRequest } from "./Types";
import { useDownloads } from "../DownloadsContext";

function RequestComponent({
  request,
  handleClose,
}: {
  request: DownloadRequest;
  handleClose: () => void;
}) {
  const { startFileDownload, retryRequest } = useDownloads();
  const { t } = useTranslation();
  const progress = Math.max(0, Math.min(100, Math.round(request.progress ?? 0)));
  const progressLabel = request.progressMessage
    ? t(`RequestComponent.progress.${request.progressMessage}`, {
        defaultValue: request.progressMessage,
      })
    : "";

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
      {request.status === "pending" && (
        <div className={styles.progressBlock}>
          <div className={styles.progressMeta}>
            <span className={styles.progressPercent}>{progress}%</span>
            {progressLabel && <span className={styles.progressStage}>{progressLabel}</span>}
          </div>
          <div
            className={styles.progressTrack}
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress}
            aria-valuetext={`${progress}% ${progressLabel}`}
          >
            <div className={styles.progressFill} style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}
      {request.message && <p className={styles.message}>{request.message}</p>}
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
