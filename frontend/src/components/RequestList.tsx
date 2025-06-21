import { Trans, useTranslation } from "react-i18next";
import styles from "./RequestList.module.css";
import { useState, useEffect } from "react";
import type { Request } from "./Types";
import { RequestStatus } from "./Types";
import { RequestComponent } from "./RequestComponent";
import Alert, { useAlert } from "./Alert";

function Requests() {
  const { t } = useTranslation();
  const [requests, setRequests] = useState<Request[]>([]);
  const { alertState, showAlert, hideAlert, confirmAction } = useAlert();

  useEffect(() => {
    const fetchRequests = async () => {
      const response = await fetch("http://localhost:3000/requests");
      const data = await response.json();
      setRequests(data);
    };
    fetchRequests();
  }, []);

  useEffect(() => {
    // Check if there are existing requests in localStorage
    const storedRequests = localStorage.getItem("requests");

    if (storedRequests) {
      try {
        const parsedRequests = JSON.parse(storedRequests);
        if (parsedRequests && parsedRequests.length > 0) {
          setRequests(parsedRequests);
          return; // Exit early if we have stored data
        }
      } catch (error) {
        console.error("Error parsing stored requests:", error);
      }
    }

    // Create dummy data only if no stored data exists
    const dummyRequests = new Array(10).fill(0).map((_, index) => ({
      id: index,
      title: `Request ${index}`,
      description: `Description ${index}`,
      status: RequestStatus.PENDING,
      createdAt: new Date().toISOString(),
    }));

    setRequests(dummyRequests);
    localStorage.setItem("requests", JSON.stringify(dummyRequests));
    console.log("Created and saved dummy requests to localStorage");
  }, []);

  const handleClearRequests = () => {
    showAlert(t("Alert.deleteRequests"), t("Alert.deleteRequestsMessage"));
  };

  const handleCloseRequest = (id: number) => {
    const request = requests.find((r) => r.id === id);
    showAlert(
      t("Alert.deleteRequest"),
      t("Alert.deleteRequestMessage", { title: request?.title }),
      id
    );
  };

  const handleConfirmAction = () => {
    if (alertState.requestId !== null) {
      // Close specific request
      const updatedRequests = requests.filter(
        (request) => request.id !== alertState.requestId
      );
      setRequests(updatedRequests);
      localStorage.setItem("requests", JSON.stringify(updatedRequests));
    } else {
      // Clear all requests
      setRequests([]);
      localStorage.removeItem("requests");
    }
  };

  return (
    <div className={styles.root}>
      <h1>
        <Trans i18nKey="Requests.requests">Requests</Trans>
        <br />
        <button onClick={handleClearRequests} className={styles.clearButton}>
          <Trans i18nKey="Requests.clearRequests">Clear Requests</Trans>
        </button>
        <ul>
          {requests.map((request) => (
            <li key={request.id}>
              <RequestComponent
                request={request}
                handleClose={() => handleCloseRequest(request.id)}
              />
            </li>
          ))}
        </ul>
      </h1>
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
