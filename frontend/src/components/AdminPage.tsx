import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Trans, useTranslation } from "react-i18next";
import { apiFetch } from "../api";
import { useNotification } from "./Notification";
import Alert, { useAlert } from "./Alert";
import ThemeSwitcher from "./ThemeSwitcher";
import LanguageSwitcher from "./LanguageSwitcher";
import type { AdminOverview } from "./Types";
import styles from "./AdminPage.module.css";

function AdminPage() {
  const { t } = useTranslation();
  const { notify } = useNotification();
  const { alertState, showAlert, hideAlert, confirmAction } = useAlert();
  const [checkingSession, setCheckingSession] = useState(true);
  const [loggedIn, setLoggedIn] = useState(false);
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [limitValue, setLimitValue] = useState(5);
  const [limitMessage, setLimitMessage] = useState("");

  const loadOverview = async () => {
    const result = await apiFetch<AdminOverview>("/api/admin/overview");
    if (result.ok) {
      setOverview(result.data);
      setLimitValue(result.data.current_limit);
      return true;
    }
    if (result.status === 401) {
      setLoggedIn(false);
    }
    return false;
  };

  useEffect(() => {
    const checkSession = async () => {
      try {
        const result = await apiFetch<{ logged_in: boolean }>("/api/admin/session");
        setLoggedIn(Boolean(result.data.logged_in));
        if (result.data.logged_in) {
          await loadOverview();
        }
      } catch {
        setLoggedIn(false);
      } finally {
        setCheckingSession(false);
      }
    };
    checkSession();
  }, []);

  const handleLogin = async (event: FormEvent) => {
    event.preventDefault();
    setLoginError("");
    const result = await apiFetch<{ status: string; message?: string; logged_in?: boolean }>(
      "/api/admin/login",
      { method: "POST", body: JSON.stringify({ password }) }
    );
    if (result.ok && result.data.logged_in) {
      setLoggedIn(true);
      setPassword("");
      await loadOverview();
      return;
    }
    setLoginError(result.data.message || t("AdminPage.invalidPassword"));
  };

  const handleLogout = async () => {
    await apiFetch("/api/admin/logout", { method: "POST" });
    setLoggedIn(false);
    setOverview(null);
  };

  const handleSetLimit = async (event: FormEvent) => {
    event.preventDefault();
    const result = await apiFetch<AdminOverview & { message?: string; concurrent_limit?: number }>(
      "/api/admin/limit",
      { method: "POST", body: JSON.stringify({ concurrent_limit: limitValue }) }
    );
    if (result.ok) {
      setOverview(result.data);
      setLimitValue(result.data.current_limit);
      setLimitMessage(result.data.message || t("AdminPage.limitUpdated"));
      notify("success", t("AdminPage.adminPage"), result.data.message || t("AdminPage.limitUpdated"));
      return;
    }
    setLimitMessage(result.data.message || t("AdminPage.invalidLimit"));
    notify("error", t("AdminPage.adminPage"), result.data.message || t("AdminPage.invalidLimit"));
  };

  const handleDeleteZips = () => {
    showAlert(t("AdminPage.deleteZipsTitle"), t("AdminPage.deleteZipsConfirm"));
  };

  const confirmDeleteZips = async () => {
    const result = await apiFetch<AdminOverview & { message?: string }>(
      "/api/admin/delete-zips",
      { method: "POST" }
    );
    if (result.ok) {
      setOverview(result.data);
      notify("success", t("AdminPage.adminPage"), result.data.message || t("AdminPage.deleteZipsSuccess"));
      return;
    }
    notify("error", t("AdminPage.adminPage"), result.data.message || t("AdminPage.deleteZipsError"));
  };

  if (checkingSession) {
    return (
      <div className={styles.root}>
        <p>
          <Trans i18nKey="AdminPage.loading">Loading...</Trans>
        </p>
      </div>
    );
  }

  if (!loggedIn) {
    return (
      <div className={styles.root}>
        <div className="page-toolbar">
          <LanguageSwitcher />
          <ThemeSwitcher />
        </div>
        <h1>
          <Trans i18nKey="AdminPage.adminPage">Admin Page</Trans>
        </h1>
        <form className={styles.loginForm} onSubmit={handleLogin}>
          <label htmlFor="admin-password">
            <Trans i18nKey="AdminPage.password">Password</Trans>
          </label>
          <input
            id="admin-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
          <button type="submit">
            <Trans i18nKey="AdminPage.login">Login</Trans>
          </button>
        </form>
        {loginError && <p className={styles.error}>{loginError}</p>}
        <Link to="/" className={styles.backLink}>
          <Trans i18nKey="AdminPage.backHome">Back to home</Trans>
        </Link>
      </div>
    );
  }

  const info = overview?.useful_info;

  return (
    <div className={styles.root}>
      <div className="page-toolbar">
        <LanguageSwitcher />
        <ThemeSwitcher />
      </div>
      <div className={styles.header}>
        <h1>
          <Trans i18nKey="AdminPage.adminPage">Admin Page</Trans>
        </h1>
        <div className={styles.headerActions}>
          <Link to="/" className={styles.backLink}>
            <Trans i18nKey="AdminPage.backHome">Back to home</Trans>
          </Link>
          <button type="button" onClick={handleLogout}>
            <Trans i18nKey="AdminPage.logout">Logout</Trans>
          </button>
        </div>
      </div>

      <section className={styles.section}>
        <h3>
          <Trans i18nKey="AdminPage.lastRequests">Last 50 Search Requests</Trans>
        </h3>
        {overview?.last_requests?.length ? (
          <ul className={styles.requestLog}>
            {overview.last_requests.map((req, index) => (
              <li key={`${req.timestamp}-${index}`}>
                <span>{req.timestamp}</span> — IP: {req.ip} — Query: "{req.search_query}"
                (Audio: {req.audio_format || "N/A"}, Lyrics: {req.lyrics_format || "N/A"}, Format: {req.output_format || "N/A"})
                — Status: {req.status_code}
              </li>
            ))}
          </ul>
        ) : (
          <p>
            <Trans i18nKey="AdminPage.noRequests">No search requests logged yet.</Trans>
          </p>
        )}
      </section>

      <section className={styles.section}>
        <h3>
          <Trans i18nKey="AdminPage.setLimit">Set Concurrent Request Limit</Trans>
        </h3>
        <form className={styles.limitForm} onSubmit={handleSetLimit}>
          <label htmlFor="concurrent_limit">
            <Trans i18nKey="AdminPage.concurrentLimit">Allowed Concurrent Requests</Trans>
          </label>
          <input
            id="concurrent_limit"
            type="number"
            min={1}
            value={limitValue}
            onChange={(event) => setLimitValue(Number(event.target.value))}
            required
          />
          <button type="submit">
            <Trans i18nKey="AdminPage.setLimitButton">Set Limit</Trans>
          </button>
        </form>
        {limitMessage && <p className={styles.message}>{limitMessage}</p>}
      </section>

      <section className={styles.section}>
        <h3>
          <Trans i18nKey="AdminPage.storageManagement">Storage Management</Trans>
        </h3>
        <button type="button" className={styles.dangerButton} onClick={handleDeleteZips}>
          <Trans i18nKey="AdminPage.deleteZips">Delete All ZIP Files</Trans>
        </button>
      </section>

      <section className={styles.section}>
        <h3>
          <Trans i18nKey="AdminPage.runningTasks">Running Download Tasks</Trans>
        </h3>
        {overview?.running_requests?.length ? (
          <ul>
            {overview.running_requests.map((id) => (
              <li key={id}>
                <Trans i18nKey="AdminPage.requestId">Request ID</Trans>: {id}
              </li>
            ))}
          </ul>
        ) : (
          <p>
            <Trans i18nKey="AdminPage.noRunning">No download tasks currently running.</Trans>
          </p>
        )}
      </section>

      <section className={styles.section}>
        <h3>
          <Trans i18nKey="AdminPage.otherInfo">Other Useful Information</Trans>
        </h3>
        {info?.storage_info_error ? (
          <p className={styles.error}>
            <Trans i18nKey="AdminPage.storageError">Error getting storage info</Trans>: {info.storage_info_error}
          </p>
        ) : (
          <>
            <h4>
              <Trans i18nKey="AdminPage.storageInfo">Storage Information</Trans>
            </h4>
            <p>
              <strong>
                <Trans i18nKey="AdminPage.musicDirPath">Music Directory Path</Trans>:
              </strong>{" "}
              <code>{info?.music_dir_path}</code>
            </p>
            <p>
              <strong>
                <Trans i18nKey="AdminPage.usedSpace">Music Directory Used Space</Trans>:
              </strong>{" "}
              {info?.music_dir_used_space_mb} MB
            </p>
            <p>
              <strong>
                <Trans i18nKey="AdminPage.zipCount">ZIP Files in Music Directory</Trans>:
              </strong>{" "}
              {info?.music_dir_zip_count}
            </p>
            <p>
              <strong>
                <Trans i18nKey="AdminPage.partitionTotal">Partition Total Space</Trans>:
              </strong>{" "}
              {info?.partition_total_space_gb} GB
            </p>
            <p>
              <strong>
                <Trans i18nKey="AdminPage.partitionFree">Partition Free Space</Trans>:
              </strong>{" "}
              {info?.partition_free_space_gb} GB
            </p>
          </>
        )}

        <h4>
          <Trans i18nKey="AdminPage.appConfig">Application Configuration</Trans>
        </h4>
        <p>
          <strong>
            <Trans i18nKey="AdminPage.effectiveLimit">Effective Concurrent Download Limit</Trans>:
          </strong>{" "}
          {info?.max_pending_requests_effective}
        </p>

        <h4>
          <Trans i18nKey="AdminPage.cleanupConfig">Cleanup Service Configuration (from Environment)</Trans>
        </h4>
        <p>
          <strong>CLEANUP_RETENTION_DAYS:</strong> {info?.cleanup_retention_days}{" "}
          <Trans i18nKey="AdminPage.days">days</Trans>
        </p>
        <p>
          <strong>AGE_CLEANUP_INTERVAL:</strong> {info?.cleanup_age_interval}{" "}
          <Trans i18nKey="AdminPage.seconds">seconds</Trans>
        </p>
        <p>
          <strong>MAX_MUSIC_DIR_SIZE_MB:</strong> {info?.cleanup_max_dir_size_mb} MB
        </p>
        <p>
          <strong>CLEANUP_TARGET_PERCENTAGE:</strong> {info?.cleanup_target_percentage}%
        </p>
        <p>
          <strong>SIZE_CHECK_INTERVAL:</strong> {info?.cleanup_size_check_interval}{" "}
          <Trans i18nKey="AdminPage.seconds">seconds</Trans>
        </p>
      </section>

      <Alert
        isOpen={alertState.isOpen}
        title={alertState.title}
        message={alertState.message}
        onConfirm={() => confirmAction(confirmDeleteZips)}
        onCancel={hideAlert}
      />
    </div>
  );
}

export default AdminPage;
