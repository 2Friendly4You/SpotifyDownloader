import { Trans } from "react-i18next";
import styles from "./RequestComponent.module.css";
import type { Request } from "./Types";

function RequestComponent({ request, handleClose }: { request: Request; handleClose: () => void }) {
  return (
    <div className={styles.root}>
      <button className={styles.closeButton} onClick={handleClose}><span><Trans i18nKey="RequestComponent.delete">×</Trans></span></button>
      <h2>{request.title}</h2>
      <p>{request.description}</p>
      <p>{request.createdAt}</p>
      <div className={styles.buttonContainer}>
        <button className={styles.downloadButton} ><Trans i18nKey="RequestComponent.download">Download</Trans></button>
      </div>
    </div>
  );
}

export { RequestComponent };
