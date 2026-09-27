import styles from "./Footer.module.css";
import { Trans } from "react-i18next";

function Footer() {
    return (
        <footer className={styles.footer}>
            <div className={styles.actions}>
                <a
                    href="https://github.com/2Friendly4You/SpotifyDownloader/issues/new?template=bug_report.yml"
                    className={styles.button}
                    target="_blank"
                    rel="noopener"
                >
                    <span className="material-symbols-outlined">bug_report</span>
                    <Trans i18nKey="Footer.reportBug">Report Bug</Trans>
                </a>
                <a
                    href="https://github.com/2Friendly4You/SpotifyDownloader/issues/new?template=feature_request.yml"
                    className={styles.button}
                    target="_blank"
                    rel="noopener"
                >
                    <span className="material-symbols-outlined">lightbulb</span>
                    <Trans i18nKey="Footer.featureRequest">Feature Request</Trans>
                </a>
            </div>
            <p className={styles.meta}>
                <a
                    href="https://github.com/2Friendly4You/SpotifyDownloader"
                    className={styles.link}
                    target="_blank"
                    rel="noopener"
                >
                    <span className="material-symbols-outlined">code</span>
                    <Trans i18nKey="Footer.viewOnGitHub">View on GitHub</Trans>
                </a>
                <span className={styles.credit}>
                    <Trans i18nKey="Footer.createdBy">Created with ❤️ by</Trans>{" "}
                    <a
                        href="https://github.com/2Friendly4You"
                        className={styles.link}
                        target="_blank"
                        rel="noopener"
                    >
                        <Trans i18nKey="Footer.author">2Friendly4You</Trans>
                    </a>
                </span>
            </p>
            <p className={styles.disclaimer}>
                <Trans i18nKey="Disclaimer">This Spotify downloader is legal for personal use only. The music may not be distributed or played in public.</Trans>
            </p>
        </footer>
    );
}

export default Footer;
