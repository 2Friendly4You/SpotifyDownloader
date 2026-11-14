import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { io, type Socket } from "socket.io-client";
import { apiFetch } from "./api";
import { useNotification } from "./components/Notification";
import i18n from "./i18n";
import { normalizeQuery, requestName } from "./requestName";
import type { DownloadRequest, FailedTrack, RequestStatus, SearchPayload } from "./components/Types";
import { serverMessage } from "./serverMessages";

const STORAGE_KEY = "userDownloads";

type StatusResponse = {
  status?: RequestStatus | "not_found";
  url?: string | null;
  message?: string;
  progress?: number;
  progress_message?: string;
  songs_done?: number;
  songs_total?: number;
  songs_running?: number;
  eta_seconds?: number;
  failed_tracks?: FailedTrack[];
  position?: number;
  title?: string;
};

type SearchResponse = {
  status?: string;
  message?: string;
  unique_id?: string;
  queued?: boolean;
  position?: number | null;
};

type ProgressEvent = {
  unique_id: string;
  progress?: number;
  message?: string;
  songs_done?: number;
  songs_total?: number;
  songs_running?: number;
  eta_seconds?: number;
};

type QueueUpdateEntry = {
  unique_id: string;
  position: number;
};

// Cancels a queued or running download. A running one is stopped and its
// files are deleted on the server.
function cancelOnServer(uniqueId: string) {
  void apiFetch(`/api/search/${uniqueId}`, { method: "DELETE" });
}

type DownloadsContextValue = {
  requests: DownloadRequest[];
  downloadCount: number;
  submitSearch: (payload: SearchPayload) => Promise<boolean>;
  removeRequest: (uniqueId: string) => void;
  clearRequests: () => void;
  retryRequest: (uniqueId: string) => Promise<boolean>;
  startFileDownload: (request: DownloadRequest) => Promise<void>;
};

const DownloadsContext = createContext<DownloadsContextValue | null>(null);

function loadStoredRequests(): DownloadRequest[] {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw) as DownloadRequest[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function persistRequests(requests: DownloadRequest[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(requests));
}

function sortRequests(requests: DownloadRequest[]) {
  return [...requests].sort((a, b) => {
    const timeDiff = new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
    return timeDiff !== 0 ? timeDiff : b.unique_id.localeCompare(a.unique_id);
  });
}

function triggerBrowserDownload(url: string) {
  const iframe = document.createElement("iframe");
  iframe.style.display = "none";
  iframe.src = url;
  document.body.appendChild(iframe);
  window.setTimeout(() => {
    iframe.remove();
  }, 2000);
}

export function DownloadsProvider({ children }: { children: ReactNode }) {
  const { notify } = useNotification();
  const [requests, setRequests] = useState<DownloadRequest[]>(() => loadStoredRequests());
  const [downloadCount, setDownloadCount] = useState(0);

  const updateRequests = useCallback((updater: (current: DownloadRequest[]) => DownloadRequest[]) => {
    setRequests((current) => {
      const next = sortRequests(updater(current));
      persistRequests(next);
      return next;
    });
  }, []);

  const upsertRequest = useCallback((nextItem: DownloadRequest) => {
    updateRequests((current) => {
      const index = current.findIndex((item) => item.unique_id === nextItem.unique_id);
      if (index === -1) {
        return [nextItem, ...current];
      }
      const copy = [...current];
      copy[index] = { ...copy[index], ...nextItem };
      return copy;
    });
  }, [updateRequests]);

  useEffect(() => {
    const loadCounter = async () => {
      try {
        const result = await apiFetch<{ total: number }>("/api/download_counter");
        setDownloadCount(result.data.total ?? 0);
      } catch {
        setDownloadCount(0);
      }
    };
    loadCounter();
  }, []);

  const refreshStored = useCallback(async () => {
    const stored = loadStoredRequests();
    if (stored.length === 0) {
      return;
    }

    const refreshed: DownloadRequest[] = [];
    for (const item of stored) {
      try {
        const result = await apiFetch<StatusResponse>(`/api/status/${item.unique_id}`);
        if (result.data.message === "File was marked completed but is now missing.") {
          continue;
        }
        if (result.status === 404 || result.data.status === "not_found") {
          if (item.status === "failed") {
            refreshed.push(item);
          }
          continue;
        }
        const nextStatus = (result.data.status as RequestStatus) || item.status;
        refreshed.push({
          ...item,
          status: nextStatus,
          url: result.data.url ?? item.url,
          message: result.data.message || item.message,
          progress: result.data.progress ?? item.progress,
          progressMessage: result.data.progress_message ?? item.progressMessage,
          songsDone: result.data.songs_done,
          songsTotal: result.data.songs_total,
          songsRunning: result.data.songs_running,
          etaSeconds: result.data.eta_seconds,
          etaReceivedAt: Date.now(),
          title: result.data.title ?? item.title,
          // The server forgets the list after a restart; keep the copy we have.
          failedTracks: result.data.failed_tracks ?? item.failedTracks,
          queuePosition: nextStatus === "queued" ? result.data.position ?? item.queuePosition : undefined,
        });
      } catch {
        refreshed.push(item);
      }
    }
    const sorted = sortRequests(refreshed);
    setRequests(sorted);
    persistRequests(sorted);
  }, []);

  useEffect(() => {
    refreshStored();
  }, [refreshStored]);

  useEffect(() => {
    const socket: Socket = io({
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
    });

    socket.on("connect", () => {
      refreshStored();
    });

    socket.on("download_progress", (data: ProgressEvent) => {
      updateRequests((current) =>
        current.map((item) =>
          item.unique_id === data.unique_id && (item.status === "pending" || item.status === "queued")
            ? {
                ...item,
                status: "pending",
                queuePosition: undefined,
                progress: data.progress ?? item.progress,
                progressMessage: data.message || item.progressMessage,
                // The server sends these with every update that has them, so a
                // missing field means the value no longer applies.
                songsDone: data.songs_done,
                songsTotal: data.songs_total,
                songsRunning: data.songs_running,
                etaSeconds: data.eta_seconds,
                etaReceivedAt: Date.now(),
              }
            : item
        )
      );
    });

    socket.on("download_title", (data: { unique_id: string; title: string }) => {
      updateRequests((current) =>
        current.map((item) => (item.unique_id === data.unique_id ? { ...item, title: data.title } : item))
      );
    });

    socket.on("download_started", (data: { unique_id: string }) => {
      updateRequests((current) =>
        current.map((item) =>
          item.unique_id === data.unique_id
            ? {
                ...item,
                status: "pending",
                queuePosition: undefined,
                progress: item.progress ?? 0,
                progressMessage: item.progressMessage || "Searching",
              }
            : item
        )
      );
    });

    socket.on("queue_update", (data: { queue?: QueueUpdateEntry[] }) => {
      const positions = new Map((data.queue ?? []).map((entry) => [entry.unique_id, entry.position]));
      updateRequests((current) =>
        current.map((item) => {
          if (item.status !== "queued") {
            return item;
          }
          const position = positions.get(item.unique_id);
          return position === undefined ? item : { ...item, queuePosition: position };
        })
      );
    });

    socket.on("download_cancelled", (data: { unique_id: string; by_admin?: boolean }) => {
      if (!data.by_admin) {
        updateRequests((current) => current.filter((item) => item.unique_id !== data.unique_id));
        return;
      }
      // Cancelled by the operator: keep the card with a reason, so it does
      // not just vanish, and the user can start it again.
      updateRequests((current) =>
        current.map((item) =>
          item.unique_id === data.unique_id
            ? {
                ...item,
                status: "failed",
                message: i18n.t("RequestComponent.cancelledByAdmin"),
                progress: undefined,
                progressMessage: undefined,
                etaSeconds: undefined,
              }
            : item
        )
      );
    });

    socket.on(
      "download_complete",
      (data: { unique_id: string; url: string; failed_tracks?: FailedTrack[]; title?: string }) => {
        updateRequests((current) =>
          current.map((item) =>
            item.unique_id === data.unique_id
              ? {
                  ...item,
                  status: "completed",
                  url: data.url,
                  message: "",
                  failedTracks: data.failed_tracks,
                  title: data.title ?? item.title,
                }
              : item
          )
        );
      }
    );

    socket.on(
      "download_failed",
      (data: {
        unique_id: string;
        message?: string;
        search_query?: string;
        zip_url?: string | null;
        failed_tracks?: FailedTrack[];
        title?: string;
      }) => {
        updateRequests((current) =>
          current.map((item) =>
            item.unique_id === data.unique_id
              ? {
                  ...item,
                  status: "failed",
                  message: data.message || item.message,
                  url: data.zip_url ?? item.url,
                  failedTracks: data.failed_tracks,
                  title: data.title ?? item.title,
                }
              : item
          )
        );
        notify(
          "error",
          i18n.t("Toasts.downloadFailedTitle"),
          `${data.title || data.search_query || ""}: ${serverMessage(data.message || "", i18n.language)}`
        );
      }
    );

    return () => {
      socket.disconnect();
    };
  }, [notify, refreshStored, updateRequests]);

  const submitSearch = useCallback(async (payload: SearchPayload) => {
    try {
      const result = await apiFetch<SearchResponse>("/api/search", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (result.ok && result.data.status === "success" && result.data.unique_id) {
        const queued = Boolean(result.data.queued);
        // A restart of something already in the list keeps its known name
        // until the server sends its own.
        const key = normalizeQuery(payload.search_query);
        const knownTitle = requests.find((item) => item.title && normalizeQuery(item.searchQuery) === key)?.title;
        upsertRequest({
          unique_id: result.data.unique_id,
          searchQuery: payload.search_query,
          title: knownTitle,
          url: null,
          status: queued ? "queued" : "pending",
          message: "",
          progress: queued ? undefined : 0,
          progressMessage: queued ? undefined : "Searching",
          queuePosition: queued ? result.data.position ?? undefined : undefined,
          timestamp: new Date().toISOString(),
          audio_format: payload.audio_format,
          lyrics_format: payload.lyrics_format,
          output_format: payload.output_format,
        });
        setDownloadCount((count) => count + 1);
        notify(
          "success",
          i18n.t(queued ? "Toasts.queuedTitle" : "Toasts.sentTitle"),
          i18n.t(queued ? "Toasts.queuedMessage" : "Toasts.sentMessage", { query: payload.search_query })
        );
        return true;
      }

      notify("error", i18n.t("Toasts.searchErrorTitle"), serverMessage(result.data.message || "", i18n.language) || i18n.t("Toasts.searchErrorMessage"));
      return false;
    } catch {
      notify("error", i18n.t("Toasts.errorTitle"), i18n.t("Toasts.networkMessage"));
      return false;
    }
  }, [notify, requests, upsertRequest]);

  const removeRequest = useCallback((uniqueId: string) => {
    updateRequests((current) => {
      const existing = current.find((item) => item.unique_id === uniqueId);
      if (existing?.status === "queued" || existing?.status === "pending") {
        cancelOnServer(uniqueId);
      }
      return current.filter((item) => item.unique_id !== uniqueId);
    });
  }, [updateRequests]);

  const clearRequests = useCallback(() => {
    setRequests((current) => {
      for (const item of current) {
        if (item.status === "queued" || item.status === "pending") {
          cancelOnServer(item.unique_id);
        }
      }
      return [];
    });
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  const retryRequest = useCallback(async (uniqueId: string) => {
    const existing = requests.find((item) => item.unique_id === uniqueId);
    if (!existing) {
      return false;
    }
    removeRequest(uniqueId);
    return submitSearch({
      search_query: existing.searchQuery,
      audio_format: existing.audio_format,
      lyrics_format: existing.lyrics_format,
      output_format: existing.output_format,
    });
  }, [removeRequest, requests, submitSearch]);

  const startFileDownload = useCallback(async (request: DownloadRequest) => {
    try {
      const result = await apiFetch<StatusResponse>(`/api/status/${request.unique_id}`);
      if (result.data.status === "completed" && (result.data.url || request.url)) {
        triggerBrowserDownload(result.data.url || request.url || "");
        notify("success", i18n.t("Toasts.downloadStartedTitle"), i18n.t("Toasts.downloadStartedMessage", { query: requestName(request) }));
        return;
      }
      if (result.data.status === "failed" && (result.data.url || request.url)) {
        triggerBrowserDownload(result.data.url || request.url || "");
        notify("info", i18n.t("Toasts.errorLogTitle"), i18n.t("Toasts.errorLogMessage", { query: requestName(request) }));
        return;
      }
      notify("error", i18n.t("Toasts.errorTitle"), i18n.t("Toasts.fileGoneMessage"));
      removeRequest(request.unique_id);
    } catch {
      notify("error", i18n.t("Toasts.errorTitle"), i18n.t("Toasts.fileGoneMessage"));
      removeRequest(request.unique_id);
    }
  }, [notify, removeRequest]);

  const value = useMemo(
    () => ({
      requests,
      downloadCount,
      submitSearch,
      removeRequest,
      clearRequests,
      retryRequest,
      startFileDownload,
    }),
    [clearRequests, downloadCount, removeRequest, requests, retryRequest, startFileDownload, submitSearch]
  );

  return <DownloadsContext.Provider value={value}>{children}</DownloadsContext.Provider>;
}

export function useDownloads() {
  const context = useContext(DownloadsContext);
  if (!context) {
    throw new Error("useDownloads must be used within DownloadsProvider");
  }
  return context;
}
