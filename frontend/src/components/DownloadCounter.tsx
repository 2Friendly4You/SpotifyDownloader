import { Trans } from "react-i18next";
import styles from "./DownloadCounter.module.css";
import { useState } from "react";
import { useEffect } from "react";

function DownloadCounter() {
    const [downloadCount, setDownloadCount] = useState(0);

    useEffect(() => {
        fetch("http://localhost:3000/downloads")
            .then(response => response.json())
            .then(data => {
                setDownloadCount(data);
            })
            .catch(error => {
                console.error(error);
            });
    }, []);

    return (
        <div className={styles.root}>
            <h1><Trans i18nKey="DownloadCounter.downloadCounter">Download Counter</Trans></h1>
            <p><Trans i18nKey="DownloadCounter.downloadCount" values={{ count: downloadCount }}>{downloadCount} Songs/ Playlists were already downloaded</Trans></p>
        </div>
    )
}

export default DownloadCounter;