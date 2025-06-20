import { Trans } from "react-i18next";
import styles from "./DownloadCounter.module.css";

function DownloadCounter() {
    return (
        <div className={styles.root}>
            <h1><Trans i18nKey="DownloadCounter.downloadCounter">Download Counter</Trans></h1>
        </div>
    )
}

export default DownloadCounter;