$(document).ready(function () {
    let requestIdCounter = 0;
    const socket = io({
        reconnection: true,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        reconnectionAttempts: Infinity
    });
    const pendingDownloads = new Map();

    const checkFileStatus = (unique_id) => {
        return new Promise((resolve, reject) => {
            $.get(`/status/${unique_id}`)
                .done(function(response) {
                    resolve(response);
                })
                .fail(function(error) {
                    reject(error);
                });
        });
    };

    // Update loadDownloadHistory to not remove pending items
    const loadDownloadHistory = () => {
        console.log("Loading download history...");
        const userDownloads = JSON.parse(localStorage.getItem('userDownloads') || '[]');
        
        $("#requests-list").empty();
        
        userDownloads.forEach(item => {
            console.log("Checking item:", item);
            const tempItem = `<li id="${item.unique_id}">
                <span>${item.searchQuery} (Checking...)</span>
                <div class="spinner-border" role="status"></div>
            </li>`;
            $("#requests-list").append(tempItem);

            $.ajax({
                url: `/status/${item.unique_id}`,
                method: 'GET',
                success: function(response) {
                    console.log("Status response:", response);
                    if (response.status === 'completed') {
                        pendingDownloads.set(item.unique_id, item.searchQuery);
                        updateRequestItem(item.unique_id, item.searchQuery, response.url);
                    } else if (response.status === 'pending') {
                        // Keep the item but update its status
                        pendingDownloads.set(item.unique_id, item.searchQuery);
                        const existingItem = $(`#${item.unique_id}`);
                        existingItem.find('span').text(`${item.searchQuery} (Pending)`);
                    } else if (response.status === 'not_found') {
                        console.log("File not found, removing from history");
                        removeDownloadFromHistory(item.unique_id);
                    }
                },
                error: function(xhr, status, error) {
                    console.log("Status check error:", error);
                    removeDownloadFromHistory(item.unique_id);
                }
            });
        });
    };

    // Save download to user's storage
    const saveDownload = (unique_id, searchQuery, url) => {
        const userDownloads = JSON.parse(localStorage.getItem('userDownloads') || '[]');
        const filteredDownloads = userDownloads.filter(d => d.unique_id !== unique_id);
        filteredDownloads.push({ unique_id, searchQuery, url });
        localStorage.setItem('userDownloads', JSON.stringify(filteredDownloads));
    };

    // Clear user's download history
    $("#clear-history").click(function() {
        localStorage.removeItem('userDownloads');
        $("#requests-list").empty();
    });

    // Socket.IO event handlers
    socket.on('connect', function() {
        console.log('Connected to server');
        loadDownloadHistory();
    });

    socket.on('download_complete', function(data) {
        console.log('Download complete:', data);
        if (pendingDownloads.has(data.unique_id)) {
            const searchQuery = pendingDownloads.get(data.unique_id);
            updateRequestItem(data.unique_id, searchQuery, data.url);
            saveDownload(data.unique_id, searchQuery, data.url);
            pendingDownloads.delete(data.unique_id);
        }
    });

    socket.on('download_status', function(data) {
        const userDownloads = JSON.parse(localStorage.getItem('userDownloads') || '[]');
        const userDownloadIds = new Set(userDownloads.map(d => d.unique_id));

        // Only handle downloads that belong to this user
        data.completed.forEach(download => {
            if (userDownloadIds.has(download.unique_id)) {
                updateRequestItem(
                    download.unique_id, 
                    pendingDownloads.get(download.unique_id), 
                    download.url
                );
            }
        });

        data.pending.forEach(download => {
            if (userDownloadIds.has(download.unique_id)) {
                const existingItem = $(`#${download.unique_id}`);
                if (existingItem.length && !existingItem.find('.spinner-border').length) {
                    existingItem.find('span').text(
                        `${pendingDownloads.get(download.unique_id)} (Pending)`
                    );
                    existingItem.append('<div class="spinner-border" role="status"></div>');
                }
            }
        });
    });

    socket.on('disconnect', function() {
        console.log('Disconnected from server, attempting to reconnect...');
    });

    socket.on('reconnect', function() {
        console.log('Reconnected to server');
    });

    // Update request item in UI with better status handling
    const updateRequestItem = (requestId, searchQuery, url) => {
        console.log('Updating request item:', requestId, searchQuery, url);
        $.ajax({
            url: `/status/${requestId}`,
            method: 'GET',
            success: function(response) {
                console.log('Status response:', response);
                const existingItem = $(`#${requestId}`);
                
                if (!existingItem.length) {
                    console.log('Item not found in DOM');
                    return;
                }

                switch(response.status) {
                    case 'completed':
                        existingItem.find('span').text(`${searchQuery} (Completed)`);
                        existingItem.find('.spinner-border').remove();
                        if (!existingItem.find('.btn-success').length) {
                            existingItem.append(`
                                <button class="btn btn-success" onclick="startDownload('${url}', '${searchQuery}', '${requestId}')">Download</button>
                            `);
                        }
                        break;
                    case 'pending':
                        console.log('Download still pending');
                        existingItem.find('span').text(`${searchQuery} (Pending)`);
                        if (!existingItem.find('.spinner-border').length) {
                            existingItem.append('<div class="spinner-border" role="status"></div>');
                        }
                        break;
                    case 'missing_file':
                        // Only remove if the server specifically says the file is missing
                        console.log('File is missing, removing from history');
                        removeDownloadFromHistory(requestId);
                        break;
                    default:
                        console.log('Unexpected status:', response.status);
                        // Don't remove for unknown statuses
                        break;
                }
            },
            error: function(xhr, status, error) {
                console.error('Status check failed:', error);
                // Don't remove on error - might be temporary server issue
            }
        });
    };

    // Add new function to remove download from history
    const removeDownloadFromHistory = (unique_id) => {
        console.log("Removing from history:", unique_id);
        const userDownloads = JSON.parse(localStorage.getItem('userDownloads') || '[]');
        const filteredDownloads = userDownloads.filter(d => d.unique_id !== unique_id);
        localStorage.setItem('userDownloads', JSON.stringify(filteredDownloads));
        $(`#${unique_id}`).fadeOut(300, function() {
            $(this).remove();
        });
        pendingDownloads.delete(unique_id);
    };

    // Handle search form submission
    const initiateDownload = async () => {
        const searchQuery = $("#search_query").val().trim();
        const audioFormat = $("#audio_format").val().trim();
        const lyricsFormat = $("#lyrics_format").val().trim();
        const outputFormat = $("#output_format").val().trim();

        if (!searchQuery || !outputFormat) {
            notificationSystem.error('Oops...', 'Please provide a search query and select an output format!');
            return;
        }

        if (searchQuery.includes("https://open.spotify.com/playlist/")) {
            await showAlert('Info...', 'Downloading a playlist can take a few minutes.', "playlistNotification");
        } else if (!searchQuery.includes("https://open.spotify.com/track/")) {
            await showAlert('Info...', 'Search queries are often very imprecise. Please use links if you want to get accurate results.', "trackNotification");
        }

        // Submit download request
        $.post('/search', {
            search_query: searchQuery,
            audio_format: audioFormat,
            lyrics_format: lyricsFormat,
            output_format: outputFormat
        })
        .done(function(data) {
            if (data.status === 'success' && data.unique_id) {
                pendingDownloads.set(data.unique_id, searchQuery);
                saveDownload(data.unique_id, searchQuery);
                
                const requestItem = `<li id="${data.unique_id}">
                    <span>${searchQuery} (Pending)</span>
                    <div class="spinner-border" role="status"></div>
                </li>`;
                $("#requests-list").append(requestItem);
                
                incrementDownloadCounter();
            }
        })
        .fail(function(jqXHR, textStatus, errorThrown) {
            console.error('Request failed:', errorThrown);
            notificationSystem.error('Error', 'Failed to start download. Please try again.');
        });

        $("#search_query").val('');
    };

    // Simplified startDownload function
    window.startDownload = function(url, filename, unique_id) {
        console.log("Starting download check for:", unique_id);
        $.ajax({
            url: `/status/${unique_id}`,
            method: 'GET',
            success: function(response) {
                console.log("Download status response:", response);
                if (response.status === 'completed') {
                    const iframe = document.createElement('iframe');
                    iframe.style.display = 'none';
                    iframe.src = url;
                    document.body.appendChild(iframe);
                    
                    setTimeout(() => {
                        document.body.removeChild(iframe);
                    }, 2000);

                    notificationSystem.success('Download Started', `Downloading ${filename}...`);
                } else {
                    console.log("File no longer available, removing from history");
                    removeDownloadFromHistory(unique_id);
                }
            },
            error: function(xhr, status, error) {
                console.log("Download check error:", error);
                notificationSystem.error('Error', 'Failed to start download. Maybe the file is no longer available.');
                removeDownloadFromHistory(unique_id);
            }
        });
    };

    // Event handlers
    $("#search-form").submit(function(event) {
        event.preventDefault();
        initiateDownload();
    });

    $("#download-button").click(initiateDownload);

    $("#search_query").keypress(function(e) {
        if (e.which === 13) {
            e.preventDefault();
            initiateDownload();
        }
    });

    $("#search_query").on('input', function() {
        updateProviders($(this).val());
    });

    // Initialize download counter
    $.get('/download_counter', function(data) {
        $("#downloadCounter").text(data);
    });
});
