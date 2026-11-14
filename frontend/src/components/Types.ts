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
  ip: string;
  search_query: string;
  audio_format: string | null;
  lyrics_format: string | null;
  output_format: string | null;
  status_code: number | null;
};

export type AdminUsefulInfo = {
  music_dir_path: string;
  music_dir_zip_count?: number;
  music_dir_used_space_mb?: number;
  partition_total_space_gb?: number;
  partition_free_space_gb?: number;
  storage_info_error?: string;
  cleanup_retention_days: string;
  max_pending_requests_effective: number;
  max_queued_requests_effective: number;
  cleanup_age_interval: string;
  cleanup_max_dir_size_mb: string;
  cleanup_target_percentage: string;
  cleanup_size_check_interval: string;
};

export type AdminOverview = {
  last_requests: AdminSearchLog[];
  running_requests: string[];
  queued_requests: string[];
  current_limit: number;
  useful_info: AdminUsefulInfo;
};
