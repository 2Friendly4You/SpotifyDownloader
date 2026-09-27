import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import styles from "./Notification.module.css";

export type ToastType = "success" | "error" | "info";

type Toast = {
  id: number;
  type: ToastType;
  title: string;
  message: string;
};

type NotificationContextValue = {
  notify: (type: ToastType, title: string, message: string) => void;
};

const NotificationContext = createContext<NotificationContextValue | null>(null);

const TOAST_DURATION = 4000;

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const notify = useCallback((type: ToastType, title: string, message: string) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, type, title, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, TOAST_DURATION);
  }, []);

  const value = useMemo(() => ({ notify }), [notify]);

  return (
    <NotificationContext.Provider value={value}>
      {children}
      <div className={styles.container} aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`${styles.toast} ${styles[toast.type]}`}>
            <strong>{toast.title}</strong>
            <p>{toast.message}</p>
          </div>
        ))}
      </div>
    </NotificationContext.Provider>
  );
}

export function useNotification() {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error("useNotification must be used within NotificationProvider");
  }
  return context;
}
