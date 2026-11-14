export type RequestStatus = "queued" | "pending" | "completed" | "failed" | "error";

export type SearchPayload = {
  search_query: string;
  audio_format: string;
  lyrics_format: string;
  output_format: string;
};

export type FailedTrackReason = "not_found" | "download_failed" | "conversion_failed" | "metadata_failed";

export type FailedTrack = {
  title: string;
  reason: FailedTrackReason | string;
  url?: string | null;
};

export type DownloadRequest = {
  unique_id: string;
  searchQuery: string;
  // Playlist, album or song name from the server; unknown at first.
  title?: string;
  url: string | null;
  status: RequestStatus;
  message: string;
  progress?: number;
  progressMessage?: string;
  songsDone?: number;
  songsTotal?: number;
  songsRunning?: number;
  etaSeconds?: number;
  // When etaSeconds arrived, so the card can count down between updates.
  etaReceivedAt?: number;
  failedTracks?: FailedTrack[];
  queuePosition?: number;
  timestamp: string;
  audio_format: string;
  lyrics_format: string;
  output_format: string;
};

export type AdminSearchLog = {
  timestamp: string;
  time?: number;
  ip: string;
  search_query: string;
  audio_format: string | null;
  lyrics_format: string | null;
  output_format: string | null;
  status_code: number | null;
};

export type AdminJobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type AdminJob = {
  id: string;
  title: string | null;
  query: string | null;
  source: "spotify" | "youtube" | null;
  format: string | null;
  provider: string | null;
  status: AdminJobStatus;
  created_at: number | null;
  started_at: number | null;
  finished_at: number | null;
  size_bytes: number | null;
  songs_total: number | null;
  songs_saved: number | null;
  message: string | null;
  file_deleted_at: number | null;
  file_available: boolean;
  failed_tracks: FailedTrack[];
  position?: number;
  progress?: {
    percent: number;
    message: string;
    songs_done?: number;
    songs_total?: number;
    songs_running?: number;
    eta_seconds?: number;
  };
};

export type AdminWindowStats = {
  completed: number;
  failed: number;
  cancelled: number;
  songs: number;
  failed_songs: number;
  bytes: number;
  avg_duration_seconds: number | null;
};

export type AdminOverview = {
  last_requests: AdminSearchLog[];
  current_limit: number;
  server_time: number;
  jobs: { running: AdminJob[]; queued: AdminJob[]; recent: AdminJob[] };
  stats: {
    total_downloads: number;
    history_since: number | null;
    day: AdminWindowStats;
    week: AdminWindowStats;
    month: AdminWindowStats;
    finishes: [number, string][];
  };
  storage: {
    zip_count: number;
    zip_bytes: number;
    oldest_zip_at: number | null;
    leftover_count: number;
    leftover_bytes: number;
    music_dir_bytes: number;
    disk_total_bytes?: number;
    disk_free_bytes?: number;
    disk_used_bytes?: number;
    error?: string;
  };
  health: {
    started_at: number;
    uptime_seconds: number;
    load_average: [number, number, number] | null;
    cpu_count: number | null;
    memory_bytes: number | null;
    ffmpeg: boolean;
    cleanup_running: boolean;
    music_dir_writable: boolean;
    versions: { spotdl: string | null; yt_dlp: string | null; python: string };
  };
  settings: {
    concurrent_limit: number;
    queue_limit: number;
    retention_days: number;
    max_music_dir_mb: number;
    cleanup_target_percent: number;
    age_cleanup_interval_seconds: number;
    size_check_interval_seconds: number;
  };
};
