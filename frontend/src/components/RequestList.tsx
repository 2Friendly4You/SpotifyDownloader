import { Trans, useTranslation } from "react-i18next";
import styles from "./RequestList.module.css";
import { RequestComponent } from "./RequestComponent";
import Alert, { useAlert } from "./Alert";
import { useDownloads } from "../DownloadsContext";

function Requests() {
  const { t } = useTranslation();
  const { requests, clearRequests, removeRequest } = useDownloads();
  const { alertState, showAlert, hideAlert, confirmAction } = useAlert();

  const handleClearRequests = () => {
    showAlert(t("Alert.deleteRequests"), t("Alert.deleteRequestsMessage"));
  };

  const handleCloseRequest = (uniqueId: string) => {
    const request = requests.find((item) => item.unique_id === uniqueId);
    showAlert(
      t("Alert.deleteRequest"),
      t("Alert.deleteRequestMessage", { title: request?.searchQuery }),
      uniqueId
    );
  };

  const handleConfirmAction = () => {
    if (alertState.requestId !== null) {
      removeRequest(String(alertState.requestId));
    } else {
      clearRequests();
    }
  };

  return (
    <div className={styles.root}>
      <h2>
        <Trans i18nKey="Requests.requests">Requests</Trans>
      </h2>
      <button onClick={handleClearRequests} className={styles.clearButton}>
        <Trans i18nKey="Requests.clearRequests">Clear Requests</Trans>
      </button>
      <ul>
        {requests.map((request) => (
          <li key={request.unique_id}>
            <RequestComponent
              request={request}
              handleClose={() => handleCloseRequest(request.unique_id)}
            />
          </li>
        ))}
      </ul>
      <Alert
        isOpen={alertState.isOpen}
        title={alertState.title}
        message={alertState.message}
        onConfirm={() => confirmAction(handleConfirmAction)}
        onCancel={hideAlert}
      />
    </div>
  );
}

export default Requests;
