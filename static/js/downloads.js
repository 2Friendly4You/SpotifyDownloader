function startDownload(url, filename) {
    const iframe = document.createElement('iframe');
    iframe.style.display = 'none';
    iframe.src = url;
    document.body.appendChild(iframe);
    
    // Remove the iframe after a short delay
    setTimeout(() => {
        document.body.removeChild(iframe);
    }, 2000);

    // Show success message
    notificationSystem.success('Download Started', `Downloading ${filename}...`);
}

function updateProviders(searchQuery) {
    const isYouTubeUrl = /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\/.+$/.test(searchQuery);
    const audioFormatSelect = $("#audio_format");
    const lyricsFormatSelect = $("#lyrics_format");
    const outputFormatSelect = $("#output_format");
    
    if (isYouTubeUrl) {
        audioFormatSelect.html('<option value="yt-dlp">YouTube Downloader</option>');
        audioFormatSelect.prop('disabled', true);
        lyricsFormatSelect.prop('disabled', true);
        outputFormatSelect.prop('disabled', false);
    } else {
        audioFormatSelect.html(`
            <option value="youtube-music">YouTube Music</option>
            <option value="youtube">YouTube</option>
            <option value="slider-kz">slider.kz</option>
            <option value="soundcloud">SoundCloud</option>
            <option value="bandcamp">Bandcamp</option>
            <option value="piped">Piped</option>
        `);
        audioFormatSelect.prop('disabled', false);
        lyricsFormatSelect.prop('disabled', false);
        outputFormatSelect.prop('disabled', false);
    }
}

function incrementDownloadCounter() {
    $("#downloadCounter").text(parseInt($("#downloadCounter").text()) + 1);
}
