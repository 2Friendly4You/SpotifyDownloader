import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { io, type Socket } from "socket.io-client";
import { apiFetch } from "./api";
import { useNotification } from "./components/Notification";
import type { DownloadRequest, RequestStatus, SearchPayload } from "./components/Types";

const STORAGE_KEY = "userDownloads";

type StatusResponse = {
  status?: RequestStatus | "not_found";
  url?: string | null;
  message?: string;
  progress?: number;
  progress_message?: string;
  position?: number;
};

type SearchResponse = {
  status?: string;
  message?: string;
  unique_id?: string;
  queued?: boolean;
  position?: number | null;
};

type QueueUpdateEntry = {
  unique_id: string;
  position: number;
};

function cancelQueuedOnServer(uniqueId: string) {
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

    socket.on("download_progress", (data: { unique_id: string; progress?: number; message?: string }) => {
      updateRequests((current) =>
        current.map((item) =>
          item.unique_id === data.unique_id && (item.status === "pending" || item.status === "queued")
            ? {
                ...item,
                status: "pending",
                queuePosition: undefined,
                progress: data.progress ?? item.progress,
                progressMessage: data.message || item.progressMessage,
              }
            : item
        )
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

    socket.on("download_complete", (data: { unique_id: string; url: string }) => {
      updateRequests((current) =>
        current.map((item) =>
          item.unique_id === data.unique_id
            ? { ...item, status: "completed", url: data.url, message: "" }
            : item
        )
      );
    });

    socket.on(
      "download_failed",
      (data: { unique_id: string; message?: string; search_query?: string; zip_url?: string | null }) => {
        updateRequests((current) =>
          current.map((item) =>
            item.unique_id === data.unique_id
              ? {
                  ...item,
                  status: "failed",
                  message: data.message || item.message,
                  url: data.zip_url ?? item.url,
                }
              : item
          )
        );
        notify("error", "Download Failed", `${data.search_query || "Item"}: ${data.message || ""}`);
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
        upsertRequest({
          unique_id: result.data.unique_id,
          searchQuery: payload.search_query,
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
          queued ? "Queued" : "Request Sent",
          queued
            ? `Download for "${payload.search_query}" is waiting for a free slot.`
            : `Download for "${payload.search_query}" has been initiated.`
        );
        return true;
      }

      notify("error", "Search Error", result.data.message || "Failed to start download.");
      return false;
    } catch {
      notify("error", "Error", "Network error or server unreachable. Please check your connection.");
      return false;
    }
  }, [notify, upsertRequest]);

  const removeRequest = useCallback((uniqueId: string) => {
    updateRequests((current) => {
      const existing = current.find((item) => item.unique_id === uniqueId);
      if (existing?.status === "queued") {
        cancelQueuedOnServer(uniqueId);
      }
      return current.filter((item) => item.unique_id !== uniqueId);
    });
  }, [updateRequests]);

  const clearRequests = useCallback(() => {
    setRequests((current) => {
      for (const item of current) {
        if (item.status === "queued") {
          cancelQueuedOnServer(item.unique_id);
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
        notify("success", "Download Started", `Downloading ${request.searchQuery}.zip...`);
        return;
      }
      if (result.data.status === "failed" && (result.data.url || request.url)) {
        triggerBrowserDownload(result.data.url || request.url || "");
        notify("info", "Error Log", `Downloading error archive for ${request.searchQuery}.`);
        return;
      }
      notify("error", "Error", "Failed to start download. Maybe the file is no longer available.");
      removeRequest(request.unique_id);
    } catch {
      notify("error", "Error", "Failed to start download. Maybe the file is no longer available.");
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
