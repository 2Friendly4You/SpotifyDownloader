import { useEffect, useState } from "react";
import styles from "./Notification.module.css";

const NOTIFICATION_DURATION = 3000;

function Message({ message, type }: { message: string, type: "success" | "error" | "info" }) {
  const [notification, setNotification] = useState<string>("");

  useEffect(() => {
    setNotification(message);
    setTimeout(() => {
      setNotification("");
    }, NOTIFICATION_DURATION);
  }, []);

  return (
    <div className={`${styles.notification} ${styles[type]}`}>
      <h1>{notification}</h1>
    </div>
  );
}

export { Message };