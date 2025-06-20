import { Trans } from "react-i18next";
import styles from "./Requests.module.css";

function Requests() {
  return (
    <div className={styles.root}>
      <h1>
        <Trans i18nKey="Requests.requests">Requests</Trans>
      </h1>
    </div>
  );
}

export default Requests;
