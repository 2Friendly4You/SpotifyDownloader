import { Trans } from "react-i18next";
import { useState, useCallback, useEffect } from "react";
import styles from "./Alert.module.css";

type AlertState = {
  isOpen: boolean;
  title: string;
  message: string;
  requestId: number | null;
};

type AlertProps = {
  isOpen: boolean;
  title: string;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
};

function Alert({ isOpen, title, message, onConfirm, onCancel }: AlertProps) {
  useEffect(() => {
    if (isOpen) {
      // Store the element that had focus before the alert opened
      const previousActiveElement = document.activeElement as HTMLElement;
      
      // Add aria-hidden to all focusable elements outside the alert
      const focusableElements = document.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      
      focusableElements.forEach((element) => {
        if (!element.closest(`.${styles.overlay}`)) {
          element.setAttribute('aria-hidden', 'true');
          element.setAttribute('tabindex', '-1');
        }
      });

      // Focus the first button in the alert
      const firstButton = document.querySelector(`.${styles.alert} button`) as HTMLElement;
      if (firstButton) {
        firstButton.focus();
      }

      // Handle escape key
      const handleEscape = (e: KeyboardEvent) => {
        if (e.key === 'Escape') {
          onCancel();
        }
      };

      document.addEventListener('keydown', handleEscape);

      // Cleanup function
      return () => {
        // Remove aria-hidden and restore tabindex
        focusableElements.forEach((element) => {
          element.removeAttribute('aria-hidden');
          const originalTabIndex = element.getAttribute('data-original-tabindex');
          if (originalTabIndex) {
            element.setAttribute('tabindex', originalTabIndex);
            element.removeAttribute('data-original-tabindex');
          } else {
            element.removeAttribute('tabindex');
          }
        });

        // Restore focus to the previous element
        if (previousActiveElement) {
          previousActiveElement.focus();
        }

        document.removeEventListener('keydown', handleEscape);
      };
    }
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onCancel();
    }
  };

  return (
    <div className={styles.overlay} onClick={handleOverlayClick}>
      <div className={styles.alert}>
        <h3>{title}</h3>
        <p>{message}</p>
        <div className={styles.buttonContainer}>
          <button onClick={onCancel} className={styles.cancelButton}>
            <Trans i18nKey="Alert.cancel">Cancel</Trans>
          </button>
          <button onClick={onConfirm} className={styles.confirmButton}>
            <Trans i18nKey="Alert.ok">OK</Trans>
          </button>
        </div>
      </div>
    </div>
  );
}

export const useAlert = () => {
  const [alertState, setAlertState] = useState<AlertState>({
    isOpen: false,
    title: "",
    message: "",
    requestId: null,
  });

  const showAlert = useCallback((title: string, message: string, requestId: number | null = null) => {
    setAlertState({
      isOpen: true,
      title,
      message,
      requestId,
    });
  }, []);

  const hideAlert = useCallback(() => {
    setAlertState({
      isOpen: false,
      title: "",
      message: "",
      requestId: null,
    });
  }, []);

  const confirmAction = useCallback((onConfirm: () => void) => {
    onConfirm();
    hideAlert();
  }, [hideAlert]);

  return {
    alertState,
    showAlert,
    hideAlert,
    confirmAction,
  };
};

export default Alert; 