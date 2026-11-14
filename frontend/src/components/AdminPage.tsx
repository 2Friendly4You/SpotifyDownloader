import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../api";
import { formatBytes, formatDateTime, formatDuration, formatRelative, groupByDay } from "../admin/format";
import { etaLabel } from "../eta";
import { useNotification } from "./Notification";
import Alert from "./Alert";
import ThemeSwitcher from "./ThemeSwitcher";
import LanguageSwitcher from "./LanguageSwitcher";
import type { AdminJob, AdminOverview } from "./Types";
import styles from "./AdminPage.module.css";
import cardStyles from "./RequestComponent.module.css";

const REFRESH_MS = 5000;
const PAGE_SIZE = 10;
const CLEANUP_AGES = [1, 3, 7, 14];

type Confirm = {
  title: string;
  message: string;
  confirmLabel: string;
  run: () => Promise<void>;
};

type Filter = "all" | "completed" | "failed" | "cancelled";

function jobName(job: AdminJob, fallback: string) {
  return job.title || job.query || fallback;
}

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHeader}>
        <h2>{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "warn" | "bad" }) {
  return (
    <div className={`${styles.kpi} ${tone ? styles[tone] : ""}`}>
      <span className={styles.kpiLabel}>{label}</span>
      <span className={styles.kpiValue}>{value}</span>
      {hint && <span className={styles.kpiHint}>{hint}</span>}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  return <span className={`${styles.badge} ${styles[`badge_${status}`] ?? ""}`}>{t(`Admin.status.${status}`)}</span>;
}

function FailedSongs({ job }: { job: AdminJob }) {
  const { t } = useTranslation();
  if (!job.failed_tracks.length) {
    return null;
  }
  return (
    <details className={cardStyles.failedTracks}>
      <summary>{t("RequestComponent.failedTracks.summary", { count: job.failed_tracks.length })}</summary>
      <ul>
        {job.failed_tracks.map((track, index) => (
          <li key={`${track.url ?? track.title}-${index}`}>
            {track.url ? (
              <a href={track.url} target="_blank" rel="noopener noreferrer" className={cardStyles.failedTitle}>
                {track.title}
              </a>
            ) : (
              <span className={cardStyles.failedTitle}>{track.title}</span>
            )}
            <span className={cardStyles.failedReason}>
              {t(`RequestComponent.failedTracks.reasons.${track.reason}`, {
                defaultValue: t("RequestComponent.failedTracks.reasons.download_failed"),
              })}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function ActiveJob({ job, onCancel }: { job: AdminJob; onCancel: (job: AdminJob) => void }) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language;
  const progress = job.progress;
  const percent = Math.max(0, Math.min(100, Math.round(progress?.percent ?? 0)));
  const stage = progress?.message
    ? t(`RequestComponent.progress.${progress.message}`, { defaultValue: progress.message })
    : "";
  const counts = progress?.songs_total ? ` ${progress.songs_done ?? 0}/${progress.songs_total}` : "";
  const etaKey = job.status === "running" ? etaLabel(progress?.eta_seconds ?? null, false) : null;
  return (
    <li className={styles.card}>
      <div className={styles.cardHeader}>
        <div className={styles.cardTitle}>
          <h3 title={jobName(job, t("Admin.unnamed"))}>{job.title || t("RequestComponent.resolvingName")}</h3>
          {job.query && job.query !== job.title && <p className={styles.source} title={job.query}>{job.query}</p>}
        </div>
        <StatusBadge status={job.status} />
      </div>
      {job.status === "running" ? (
        <div className={cardStyles.progressBlock}>
          <div className={cardStyles.progressMeta}>
            <span className={cardStyles.progressPercent}>{percent}%</span>
            <span className={cardStyles.progressStage}>{`${stage}${counts}`}</span>
          </div>
          <div className={cardStyles.progressTrack}>
            <div className={cardStyles.progressFill} style={{ width: `${percent}%` }} />
          </div>
        </div>
      ) : (
        <p className={styles.meta}>{t("Admin.queuePosition", { position: job.position })}</p>
      )}
      <p className={styles.meta}>
        {job.status === "running"
          ? t("Admin.runningFor", { duration: formatDuration(Date.now() / 1000 - (job.started_at ?? job.created_at ?? Date.now() / 1000)) })
          : t("Admin.waitingSince", { when: formatRelative(job.created_at, locale) })}
        {etaKey && ` · ${t(`RequestComponent.eta.${etaKey.key}`, { value: etaKey.value.toLocaleString(locale) })}`}
        {job.format && ` · ${job.format.toUpperCase()}`}
      </p>
      <div className={styles.actions}>
        <button type="button" className={styles.secondaryButton} onClick={() => onCancel(job)}>
          {t("Admin.cancelJob")}
        </button>
      </div>
    </li>
  );
}

function RecentJob({ job, onDelete }: { job: AdminJob; onDelete: (job: AdminJob) => void }) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language;
  const duration = job.finished_at && job.started_at ? formatDuration(job.finished_at - job.started_at) : "–";
  const songs =
    job.songs_saved != null
      ? t("Admin.songsSaved", { count: job.songs_saved })
      : job.songs_total != null
        ? t("Admin.songsSaved", { count: job.songs_total })
        : null;
  return (
    <li className={styles.card}>
      <div className={styles.cardHeader}>
        <div className={styles.cardTitle}>
          <h3 title={jobName(job, t("Admin.unnamed"))}>{jobName(job, t("Admin.unnamed"))}</h3>
          {job.query && job.query !== job.title ? (
            <p className={styles.source} title={job.query}>{job.query}</p>
          ) : (
            !job.query && <p className={styles.source}>{t("Admin.fileId", { id: job.id })}</p>
          )}
        </div>
        <StatusBadge status={job.status} />
      </div>
      <p className={styles.factLine}>
        <span title={formatDateTime(job.finished_at ?? job.created_at, locale)}>
          {formatRelative(job.finished_at ?? job.created_at, locale)}
        </span>
        {duration !== "–" && <span>{t("Admin.tookDuration", { duration })}</span>}
        {job.status === "completed" && job.size_bytes != null && <span>{formatBytes(job.size_bytes, locale)}</span>}
        {songs && <span>{songs}</span>}
        {job.format && <span>{job.format.toUpperCase()}</span>}
      </p>
      {job.status === "failed" && job.message && <p className={styles.errorText}>{job.message}</p>}
      <FailedSongs job={job} />
      {job.status === "completed" && (
        <div className={styles.actions}>
          {job.file_available ? (
            <>
              <a className={styles.primaryLink} href={`/api/download/${job.id}`}>
                {t("RequestComponent.download")}
              </a>
              <button type="button" className={styles.secondaryButton} onClick={() => onDelete(job)}>
                {t("Admin.deleteFile")}
              </button>
            </>
          ) : (
            <span className={styles.meta}>{job.file_deleted_at ? t("Admin.fileDeleted") : t("Admin.fileGone")}</span>
          )}
        </div>
      )}
    </li>
  );
}

function DayChart({ finishes }: { finishes: [number, string][] }) {
  const { t, i18n } = useTranslation();
  const days = useMemo(() => groupByDay(finishes, 14), [finishes]);
  const max = Math.max(1, ...days.map((d) => d.completed + d.failed + d.cancelled));
  return (
    <div className={styles.chart} role="img" aria-label={t("Admin.chartLabel")}>
      {days.map((day) => {
        const total = day.completed + day.failed + day.cancelled;
        const label = day.date.toLocaleDateString(i18n.language, { weekday: "short", day: "numeric", month: "numeric" });
        return (
          <div
            key={day.key}
            className={styles.chartDay}
            title={`${label}: ${t("Admin.chartTooltip", { completed: day.completed, failed: day.failed, cancelled: day.cancelled })}`}
          >
            <div className={styles.chartBar} style={{ height: `${(total / max) * 100}%` }}>
              {day.failed + day.cancelled > 0 && (
                <span
                  className={styles.chartFailed}
                  style={{ height: `${((day.failed + day.cancelled) / Math.max(total, 1)) * 100}%` }}
                />
              )}
            </div>
            <span className={styles.chartLabel}>{day.date.getDate()}.</span>
          </div>
        );
      })}
    </div>
  );
}

function AdminPage() {
  const { t, i18n } = useTranslation();
  const locale = i18n.language;
  const { notify } = useNotification();
  const [checkingSession, setCheckingSession] = useState(true);
  const [loggedIn, setLoggedIn] = useState(false);
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [limitValue, setLimitValue] = useState(5);
  const [limitDirty, setLimitDirty] = useState(false);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [visible, setVisible] = useState(PAGE_SIZE);
  const [cleanupAge, setCleanupAge] = useState(7);
  // The 5 s refresh must not overwrite the limit field while it is being edited.
  const limitDirtyRef = useRef(false);

  const apply = useCallback((data: AdminOverview) => {
    setOverview(data);
    setLoadedAt(Date.now());
    setLimitValue((current) => (limitDirtyRef.current ? current : data.current_limit));
  }, []);

  const loadOverview = useCallback(async () => {
    try {
      const result = await apiFetch<AdminOverview>("/api/admin/overview");
      if (result.ok) {
        apply(result.data);
        return true;
      }
      if (result.status === 401) {
        setLoggedIn(false);
        setOverview(null);
      }
    } catch {
      // Network hiccup: keep showing the last data, the next refresh retries.
    }
    return false;
  }, [apply]);

  useEffect(() => {
    limitDirtyRef.current = limitDirty;
  }, [limitDirty]);

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
  }, [loadOverview]);

  // Refresh while the tab is visible, so running jobs move on their own.
  useEffect(() => {
    if (!loggedIn) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        loadOverview();
      }
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [loggedIn, loadOverview]);

  const handleLogin = async (event: FormEvent) => {
    event.preventDefault();
    setLoginError("");
    const result = await apiFetch<{ logged_in?: boolean }>("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    });
    if (result.ok && result.data.logged_in) {
      setLoggedIn(true);
      setPassword("");
      await loadOverview();
      return;
    }
    setLoginError(t("Admin.invalidPassword"));
  };

  const handleLogout = async () => {
    await apiFetch("/api/admin/logout", { method: "POST" });
    setLoggedIn(false);
    setOverview(null);
  };

  // One helper for every action: POST, take the fresh overview from the
  // answer, and say what happened.
  const post = async (path: string, body: unknown, success: (data: Record<string, number>) => string) => {
    const result = await apiFetch<AdminOverview & Record<string, number> & { message?: string }>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (result.status === 401) {
      setLoggedIn(false);
      return false;
    }
    if (result.ok) {
      apply(result.data);
      notify("success", t("Admin.title"), success(result.data));
      return true;
    }
    notify("error", t("Admin.title"), result.data.message || t("Admin.actionFailed"));
    await loadOverview();
    return false;
  };

  const askCancel = (job: AdminJob) =>
    setConfirm({
      title: t("Admin.cancelTitle"),
      message: t("Admin.cancelMessage", { name: jobName(job, t("Admin.unnamed")) }),
      confirmLabel: t("Admin.cancelJob"),
      run: async () => {
        await post(`/api/admin/jobs/${job.id}/cancel`, undefined, () => t("Admin.cancelDone", { name: jobName(job, t("Admin.unnamed")) }));
      },
    });

  const askDelete = (job: AdminJob) =>
    setConfirm({
      title: t("Admin.deleteFileTitle"),
      message: t("Admin.deleteFileMessage", { name: jobName(job, t("Admin.unnamed")), size: formatBytes(job.size_bytes, locale) }),
      confirmLabel: t("Admin.deleteFile"),
      run: async () => {
        await post(`/api/admin/jobs/${job.id}/delete-file`, undefined, (data) =>
          t("Admin.freed", { size: formatBytes(data.freed_bytes, locale) })
        );
      },
    });

  const askCleanup = (older: number | null, leftovers: boolean, message: string) =>
    setConfirm({
      title: t("Admin.cleanupTitle"),
      message,
      confirmLabel: t("Admin.cleanupConfirm"),
      run: async () => {
        await post("/api/admin/cleanup", { older_than_days: older, leftovers }, (data) =>
          t("Admin.cleanupDone", {
            files: data.deleted_count,
            folders: data.folder_count,
            size: formatBytes(data.freed_bytes, locale),
          })
        );
      },
    });

  const askDeleteAll = () => {
    const storage = overview?.storage;
    setConfirm({
      title: t("Admin.deleteAllTitle"),
      message: t("Admin.deleteAllMessage", {
        count: storage?.zip_count ?? 0,
        size: formatBytes(storage?.zip_bytes, locale),
      }),
      confirmLabel: t("Admin.deleteAll"),
      run: async () => {
        await post("/api/admin/delete-zips", undefined, (data) =>
          t("Admin.cleanupDone", { files: data.deleted_count, folders: 0, size: formatBytes(data.freed_bytes, locale) })
        );
      },
    });
  };

  const handleSetLimit = async (event: FormEvent) => {
    event.preventDefault();
    const ok = await post("/api/admin/limit", { concurrent_limit: limitValue }, () =>
      t("Admin.limitSaved", { limit: limitValue })
    );
    if (ok) {
      setLimitDirty(false);
    }
  };

  const recent = useMemo(() => {
    const list = overview?.jobs.recent ?? [];
    const needle = query.trim().toLowerCase();
    return list.filter(
      (job) =>
        (filter === "all" || job.status === filter) &&
        (!needle || `${job.title ?? ""} ${job.query ?? ""}`.toLowerCase().includes(needle))
    );
  }, [overview, filter, query]);

  if (checkingSession) {
    return (
      <div className="container">
        <p>{t("Admin.loading")}</p>
      </div>
    );
  }

  const toolbar = (
    <div className="page-toolbar">
      <LanguageSwitcher />
      <ThemeSwitcher />
    </div>
  );

  if (!loggedIn) {
    return (
      <div className="container">
        {toolbar}
        <h1>{t("Admin.title")}</h1>
        <form className={styles.loginCard} onSubmit={handleLogin}>
          <p className={styles.meta}>{t("Admin.loginHint")}</p>
          <label htmlFor="admin-password">{t("Admin.password")}</label>
          <input
            id="admin-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
          {loginError && <p className={styles.errorText} role="alert">{loginError}</p>}
          <button type="submit" className="full-width">
            {t("Admin.login")}
          </button>
          <Link to="/" className={styles.textLink}>
            {t("Admin.backHome")}
          </Link>
        </form>
      </div>
    );
  }

  if (!overview) {
    return (
      <div className="container">
        {toolbar}
        <p>{t("Admin.loading")}</p>
      </div>
    );
  }

  const { jobs, stats, storage, health, settings } = overview;
  const active = [...jobs.running, ...jobs.queued];
  const diskUsedPercent =
    storage.disk_total_bytes && storage.disk_used_bytes != null
      ? Math.round((storage.disk_used_bytes / storage.disk_total_bytes) * 100)
      : null;
  const musicPercent =
    storage.disk_total_bytes ? Math.max(0.5, (storage.music_dir_bytes / storage.disk_total_bytes) * 100) : 0;
  const monthFinished = stats.month.completed + stats.month.failed;
  const successRate = monthFinished ? Math.round((stats.month.completed / monthFinished) * 100) : null;
  const healthItems: [string, boolean | string, boolean?][] = [
    [t("Admin.health.ffmpeg"), health.ffmpeg],
    [t("Admin.health.cleanup"), health.cleanup_running],
    [t("Admin.health.writable"), health.music_dir_writable],
  ];

  return (
    <div className={`container ${styles.page}`}>
      {toolbar}
      <header className={styles.header}>
        <div>
          <h1>{t("Admin.title")}</h1>
          <p className={styles.meta}>
            {t("Admin.updated", { when: loadedAt ? new Date(loadedAt).toLocaleTimeString(locale) : "–" })}
          </p>
        </div>
        <div className={styles.headerActions}>
          <Link to="/" className={styles.secondaryButton}>
            {t("Admin.backHome")}
          </Link>
          <button type="button" className={styles.secondaryButton} onClick={handleLogout}>
            {t("Admin.logout")}
          </button>
        </div>
      </header>

      <div className={styles.kpis}>
        <Kpi
          label={t("Admin.kpi.running")}
          value={`${jobs.running.length} / ${settings.concurrent_limit}`}
          hint={t("Admin.kpi.queued", { count: jobs.queued.length, max: settings.queue_limit })}
          tone={jobs.queued.length ? "warn" : undefined}
        />
        <Kpi
          label={t("Admin.kpi.today")}
          value={String(stats.day.completed)}
          hint={t("Admin.kpi.todayHint", { failed: stats.day.failed, songs: stats.day.songs })}
          tone={stats.day.failed > stats.day.completed ? "bad" : undefined}
        />
        <Kpi
          label={t("Admin.kpi.storage")}
          value={formatBytes(storage.music_dir_bytes, locale)}
          hint={t("Admin.kpi.zips", { count: storage.zip_count })}
        />
        <Kpi
          label={t("Admin.kpi.disk")}
          value={formatBytes(storage.disk_free_bytes, locale)}
          hint={diskUsedPercent != null ? t("Admin.kpi.diskHint", { percent: diskUsedPercent }) : undefined}
          tone={diskUsedPercent != null && diskUsedPercent >= 90 ? "bad" : diskUsedPercent != null && diskUsedPercent >= 80 ? "warn" : undefined}
        />
      </div>

      <Section title={t("Admin.active")}>
        {active.length ? (
          <ul className={styles.list}>
            {active.map((job) => (
              <ActiveJob key={job.id} job={job} onCancel={askCancel} />
            ))}
          </ul>
        ) : (
          <p className={styles.empty}>{t("Admin.noActive")}</p>
        )}
      </Section>

      <Section
        title={t("Admin.recent")}
        aside={<span className={styles.meta}>{t("Admin.recentCount", { count: jobs.recent.length })}</span>}
      >
        <div className={styles.filters}>
          <div className={styles.chips} role="group" aria-label={t("Admin.filterLabel")}>
            {(["all", "completed", "failed", "cancelled"] as Filter[]).map((value) => (
              <button
                key={value}
                type="button"
                className={`${styles.chip} ${filter === value ? styles.chipActive : ""}`}
                aria-pressed={filter === value}
                onClick={() => {
                  setFilter(value);
                  setVisible(PAGE_SIZE);
                }}
              >
                {t(`Admin.filter.${value}`)}
              </button>
            ))}
          </div>
          <input
            type="search"
            className={styles.search}
            placeholder={t("Admin.searchPlaceholder")}
            aria-label={t("Admin.searchPlaceholder")}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setVisible(PAGE_SIZE);
            }}
          />
        </div>
        {recent.length ? (
          <>
            <ul className={styles.list}>
              {recent.slice(0, visible).map((job) => (
                <RecentJob key={job.id} job={job} onDelete={askDelete} />
              ))}
            </ul>
            {recent.length > visible && (
              <button type="button" className={`${styles.secondaryButton} full-width`} onClick={() => setVisible((v) => v + PAGE_SIZE)}>
                {t("Admin.showMore", { count: recent.length - visible })}
              </button>
            )}
          </>
        ) : (
          <p className={styles.empty}>{jobs.recent.length ? t("Admin.noMatch") : t("Admin.noHistory")}</p>
        )}
      </Section>

      <Section title={t("Admin.stats")}>
        <div className={styles.card}>
          <div className={styles.chartHeader}>
            <h3>{t("Admin.chartTitle")}</h3>
            <span className={styles.legend}>
              <span className={styles.legendOk}>{t("Admin.status.completed")}</span>
              <span className={styles.legendBad}>{t("Admin.chartFailedLegend")}</span>
            </span>
          </div>
          <DayChart finishes={stats.finishes} />
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col" />
                <th scope="col">{t("Admin.period.day")}</th>
                <th scope="col">{t("Admin.period.week")}</th>
                <th scope="col">{t("Admin.period.month")}</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ["completed", (w) => String(w.completed)],
                  ["failed", (w) => String(w.failed)],
                  ["cancelled", (w) => String(w.cancelled)],
                  ["songs", (w) => String(w.songs)],
                  ["failedSongs", (w) => String(w.failed_songs)],
                  ["volume", (w) => formatBytes(w.bytes, locale)],
                  ["avgDuration", (w) => formatDuration(w.avg_duration_seconds)],
                ] as [string, (w: AdminOverview["stats"]["day"]) => string][]
              ).map(([key, value]) => (
                <tr key={key}>
                  <th scope="row">{t(`Admin.row.${key}`)}</th>
                  <td>{value(stats.day)}</td>
                  <td>{value(stats.week)}</td>
                  <td>{value(stats.month)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className={styles.meta}>
          {t("Admin.totals", { total: stats.total_downloads.toLocaleString(locale) })}
          {successRate != null && ` · ${t("Admin.successRate", { percent: successRate })}`}
          {stats.history_since && ` · ${t("Admin.historySince", { date: formatDateTime(stats.history_since, locale) })}`}
        </p>
      </Section>

      <Section title={t("Admin.storage")}>
        <div className={styles.card}>
          {storage.disk_total_bytes ? (
            <>
              <div className={styles.diskBar} aria-hidden="true">
                <span className={styles.diskOther} style={{ width: `${diskUsedPercent ?? 0}%` }} />
                <span className={styles.diskMusic} style={{ width: `${musicPercent}%` }} />
              </div>
              <p className={styles.meta}>
                {t("Admin.diskSummary", {
                  used: formatBytes(storage.disk_used_bytes, locale),
                  total: formatBytes(storage.disk_total_bytes, locale),
                  free: formatBytes(storage.disk_free_bytes, locale),
                })}
              </p>
            </>
          ) : (
            <p className={styles.errorText}>{t("Admin.diskUnavailable")}</p>
          )}
          <dl className={styles.facts}>
            <div>
              <dt>{t("Admin.zipFiles")}</dt>
              <dd>
                {storage.zip_count} · {formatBytes(storage.zip_bytes, locale)}
              </dd>
            </div>
            <div>
              <dt>{t("Admin.oldestZip")}</dt>
              <dd title={formatDateTime(storage.oldest_zip_at, locale)}>{formatRelative(storage.oldest_zip_at, locale)}</dd>
            </div>
            <div>
              <dt>{t("Admin.leftovers")}</dt>
              <dd>
                {storage.leftover_count} · {formatBytes(storage.leftover_bytes, locale)}
              </dd>
            </div>
            <div>
              <dt>{t("Admin.autoCleanup")}</dt>
              <dd>{t("Admin.autoCleanupValue", { days: settings.retention_days })}</dd>
            </div>
          </dl>
        </div>
        <div className={styles.card}>
          <h3>{t("Admin.cleanup")}</h3>
          <div className={styles.cleanupRow}>
            <label htmlFor="cleanup-age" className={styles.inlineLabel}>
              {t("Admin.cleanupOlder")}
            </label>
            <select id="cleanup-age" value={cleanupAge} onChange={(event) => setCleanupAge(Number(event.target.value))}>
              {CLEANUP_AGES.map((days) => (
                <option key={days} value={days}>
                  {t("Admin.days", { count: days })}
                </option>
              ))}
            </select>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={() => askCleanup(cleanupAge, false, t("Admin.cleanupOlderMessage", { count: cleanupAge }))}
            >
              {t("Admin.cleanupRun")}
            </button>
          </div>
          <div className={styles.cleanupRow}>
            <span className={styles.inlineLabel}>
              {t("Admin.leftoversHint", { count: storage.leftover_count, size: formatBytes(storage.leftover_bytes, locale) })}
            </span>
            <button
              type="button"
              className={styles.secondaryButton}
              disabled={!storage.leftover_count}
              onClick={() =>
                askCleanup(null, true, t("Admin.cleanupLeftoversMessage", { count: storage.leftover_count }))
              }
            >
              {t("Admin.cleanupLeftovers")}
            </button>
          </div>
          <div className={styles.dangerZone}>
            <span className={styles.inlineLabel}>{t("Admin.deleteAllHint")}</span>
            <button type="button" className={styles.dangerButton} disabled={!storage.zip_count} onClick={askDeleteAll}>
              {t("Admin.deleteAll")}
            </button>
          </div>
        </div>
      </Section>

      <Section title={t("Admin.settings")}>
        <form className={styles.card} onSubmit={handleSetLimit}>
          <label htmlFor="concurrent_limit">{t("Admin.limitLabel")}</label>
          <p className={styles.meta}>{t("Admin.limitHint")}</p>
          <div className={styles.limitRow}>
            <input
              id="concurrent_limit"
              type="number"
              min={1}
              max={50}
              value={limitValue}
              onChange={(event) => {
                setLimitValue(Number(event.target.value));
                setLimitDirty(true);
              }}
              required
            />
            <button type="submit" disabled={!limitDirty || limitValue === settings.concurrent_limit}>
              {t("Admin.save")}
            </button>
          </div>
        </form>
        <dl className={`${styles.card} ${styles.facts}`}>
          <div>
            <dt>{t("Admin.setting.queue")}</dt>
            <dd>{settings.queue_limit}</dd>
          </div>
          <div>
            <dt>{t("Admin.setting.retention")}</dt>
            <dd>{t("Admin.days", { count: settings.retention_days })}</dd>
          </div>
          <div>
            <dt>{t("Admin.setting.maxSize")}</dt>
            <dd>
              {settings.max_music_dir_mb
                ? t("Admin.maxSizeValue", {
                    size: formatBytes(settings.max_music_dir_mb * 1024 * 1024, locale),
                    percent: settings.cleanup_target_percent,
                  })
                : t("Admin.off")}
            </dd>
          </div>
          <div>
            <dt>{t("Admin.setting.interval")}</dt>
            <dd>{formatDuration(settings.age_cleanup_interval_seconds)}</dd>
          </div>
        </dl>
        <p className={styles.meta}>{t("Admin.settingsEnvHint")}</p>
      </Section>

      <Section title={t("Admin.server")}>
        <dl className={`${styles.card} ${styles.facts}`}>
          <div>
            <dt>{t("Admin.health.uptime")}</dt>
            <dd title={formatDateTime(health.started_at, locale)}>{formatDuration(health.uptime_seconds)}</dd>
          </div>
          <div>
            <dt>{t("Admin.health.load")}</dt>
            <dd>
              {health.load_average
                ? `${health.load_average.map((v) => v.toLocaleString(locale, { maximumFractionDigits: 2 })).join(" · ")}${health.cpu_count ? ` (${t("Admin.health.cpus", { count: health.cpu_count })})` : ""}`
                : "–"}
            </dd>
          </div>
          <div>
            <dt>{t("Admin.health.memory")}</dt>
            <dd>{formatBytes(health.memory_bytes, locale)}</dd>
          </div>
          <div className={styles.wideFact}>
            <dt>{t("Admin.health.versions")}</dt>
            <dd>
              spotDL {health.versions.spotdl ?? "?"} · yt-dlp {health.versions.yt_dlp ?? "?"} · Python {health.versions.python}
            </dd>
          </div>
          {healthItems.map(([label, ok]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd className={ok ? styles.ok : styles.bad}>{ok ? t("Admin.health.ok") : t("Admin.health.problem")}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section title={t("Admin.requestLog")}>
        <details className={styles.card}>
          <summary>{t("Admin.requestLogSummary", { count: overview.last_requests.length })}</summary>
          {overview.last_requests.length ? (
            <ul className={styles.logList}>
              {overview.last_requests.map((entry, index) => (
                <li key={`${entry.timestamp}-${index}`}>
                  <span className={`${styles.badge} ${entry.status_code === 202 ? styles.badge_completed : styles.badge_failed}`}>
                    {entry.status_code ?? "–"}
                  </span>
                  <span className={styles.logQuery} title={entry.search_query}>
                    {entry.search_query || "–"}
                  </span>
                  <span className={styles.meta}>
                    {entry.time ? formatDateTime(entry.time, locale) : entry.timestamp}
                    {entry.output_format && ` · ${entry.output_format.toUpperCase()}`}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.empty}>{t("Admin.noRequests")}</p>
          )}
        </details>
      </Section>

      <Alert
        isOpen={Boolean(confirm)}
        title={confirm?.title ?? ""}
        message={confirm?.message ?? ""}
        confirmLabel={confirm?.confirmLabel}
        cancelLabel={t("Admin.back")}
        danger
        onConfirm={() => {
          const action = confirm;
          setConfirm(null);
          action?.run();
        }}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}

export default AdminPage;
