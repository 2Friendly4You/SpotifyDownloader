import { Trans } from "react-i18next";
import styles from "./DownloadCounter.module.css";
import { useDownloads } from "../DownloadsContext";

function DownloadCounter() {
  const { downloadCount } = useDownloads();

  return (
    <div className={styles.root}>
      <h3>
        <Trans i18nKey="DownloadCounter.downloadCounter">Download Counter</Trans>
      </h3>
      <p>
        <Trans i18nKey="DownloadCounter.downloadCount" values={{ count: downloadCount }}>
          {downloadCount} Songs/ Playlists were already downloaded
        </Trans>
      </p>
    </div>
  );
}

export default DownloadCounter;
