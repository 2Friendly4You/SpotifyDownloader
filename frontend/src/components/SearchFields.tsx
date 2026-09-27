import { useMemo, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { useDownloads } from "../DownloadsContext";
import { spotifyResource } from "../spotifyUrl";
import { useNotification } from "./Notification";
import Alert, { useAlert } from "./Alert";
import styles from "./SearchFields.module.css";

const AUDIO_PROVIDERS = [
  { value: "youtube-music", label: "YouTube Music" },
  { value: "youtube", label: "YouTube" },
  { value: "soundcloud", label: "SoundCloud" },
  { value: "bandcamp", label: "Bandcamp" },
  { value: "piped", label: "Piped" },
];

const LYRICS_PROVIDERS = [
  { value: "musixmatch", label: "musixmatch" },
  { value: "genius", label: "genius" },
  { value: "azlyrics", label: "azlyrics" },
  { value: "synced", label: "synced" },
];

const OUTPUT_FORMATS = ["mp3", "m4a", "wav", "flac", "ogg", "opus"];

const YOUTUBE_REGEX = /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\/.+$/;

function SearchFields() {
  const { t } = useTranslation();
  const { submitSearch } = useDownloads();
  const { notify } = useNotification();
  const { alertState, showAlert, hideAlert, confirmAction } = useAlert();
  const [query, setQuery] = useState("");
  const [audioFormat, setAudioFormat] = useState("youtube-music");
  const [lyricsFormat, setLyricsFormat] = useState("musixmatch");
  const [outputFormat, setOutputFormat] = useState("mp3");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isYouTubeUrl = useMemo(() => YOUTUBE_REGEX.test(query.trim()), [query]);

  const startDownload = async () => {
    const searchQuery = query.trim();
    if (!searchQuery || !outputFormat) {
      notify("error", t("SearchFields.missingTitle"), t("SearchFields.missingMessage"));
      return;
    }

    const playlistKey = "playlistNotification";
    const trackKey = "trackNotification";
    const resource = spotifyResource(searchQuery);
    if (resource === "playlist" && !localStorage.getItem(playlistKey)) {
      showAlert(t("SearchFields.playlistTitle"), t("SearchFields.playlistMessage"), playlistKey);
      return;
    }
    if (resource !== "track" && !isYouTubeUrl && !localStorage.getItem(trackKey)) {
      showAlert(t("SearchFields.impreciseTitle"), t("SearchFields.impreciseMessage"), trackKey);
      return;
    }

    await sendSearch(searchQuery);
  };

  const sendSearch = async (searchQuery: string) => {
    setIsSubmitting(true);
    const success = await submitSearch({
      search_query: searchQuery,
      audio_format: isYouTubeUrl ? "yt-dlp" : audioFormat,
      lyrics_format: lyricsFormat,
      output_format: outputFormat,
    });
    if (success) {
      setQuery("");
    }
    setIsSubmitting(false);
  };

  const handleConfirm = () => {
    confirmAction(async () => {
      if (alertState.requestId) {
        localStorage.setItem(String(alertState.requestId), "true");
      }
      const searchQuery = query.trim();
      if (searchQuery) {
        await sendSearch(searchQuery);
      }
    });
  };

  return (
    <div className={styles.root}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          startDownload();
        }}
      >
        <div className="form-group">
          <label htmlFor="search_query">
            <Trans i18nKey="SearchFields.queryLabel">Search for a song or URL</Trans>
          </label>
          <input
            id="search_query"
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("SearchFields.search")}
          />
        </div>
        <div className="form-grid">
          <div className="form-group">
            <label htmlFor="audio_format">
              <Trans i18nKey="SearchFields.audioLabel">Audio provider</Trans>
            </label>
            <select
              id="audio_format"
              value={isYouTubeUrl ? "yt-dlp" : audioFormat}
              onChange={(event) => setAudioFormat(event.target.value)}
              disabled={isYouTubeUrl}
            >
              {isYouTubeUrl ? (
                <option value="yt-dlp">YouTube Downloader</option>
              ) : (
                AUDIO_PROVIDERS.map((provider) => (
                  <option key={provider.value} value={provider.value}>
                    {provider.label}
                  </option>
                ))
              )}
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="lyrics_format">
              <Trans i18nKey="SearchFields.lyricsLabel">Lyrics provider</Trans>
            </label>
            <select
              id="lyrics_format"
              value={lyricsFormat}
              onChange={(event) => setLyricsFormat(event.target.value)}
              disabled={isYouTubeUrl}
            >
              {LYRICS_PROVIDERS.map((provider) => (
                <option key={provider.value} value={provider.value}>
                  {provider.label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="output_format">
              <Trans i18nKey="SearchFields.outputLabel">Output format</Trans>
            </label>
            <select
              id="output_format"
              value={outputFormat}
              onChange={(event) => setOutputFormat(event.target.value)}
            >
              {OUTPUT_FORMATS.map((format) => (
                <option key={format} value={format}>
                  {format.toUpperCase()}
                </option>
              ))}
            </select>
          </div>
        </div>
        <button type="submit" className="full-width" disabled={isSubmitting}>
          <Trans i18nKey="SearchFields.search">Search</Trans>
        </button>
      </form>
      <Alert
        isOpen={alertState.isOpen}
        title={alertState.title}
        message={alertState.message}
        onConfirm={handleConfirm}
        onCancel={hideAlert}
      />
    </div>
  );
}

export default SearchFields;
