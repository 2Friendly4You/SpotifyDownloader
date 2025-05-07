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
        const userDownloads = JSON.parse(localStorage.getItem('userDownloads') || '[]').sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
        
        $("#requests-list").empty();
        
        userDownloads.forEach(item => {
            console.log("Loading item from history:", item);
            // Initial display based on stored status
            let initialDisplay = `<li id="${item.unique_id}"><span>${item.searchQuery} (${item.status || 'Checking...'})</span>`;
            if (item.status === 'pending') {
                initialDisplay += ` <div class="spinner-border spinner-border-sm" role="status"></div>`;
            }
            initialDisplay += `</li>`;
            $("#requests-list").append(initialDisplay);

            // Then verify/update status with the server
            $.ajax({
                url: `/status/${item.unique_id}`,
                method: 'GET',
                success: function(response) { // jQuery .done() equivalent
                    console.log("Status response for " + item.searchQuery + " (" + item.unique_id + "):", response);
                    
                    if (response.status === 'not_found' || 
                        (response.status === 'error' && response.message === 'File was marked completed but is now missing.')) {
                        console.log(`Item ${item.unique_id} (${item.searchQuery}) considered gone (status: ${response.status}). Removing from history.`);
                        removeDownloadFromHistory(item.unique_id);
                    } else {
                        // Ensure it's still in pendingDownloads map if it's pending, otherwise updateRequestItem handles removal from map for final states
                        if(response.status === 'pending'){
                            pendingDownloads.set(item.unique_id, item.searchQuery);
                        }
                        updateRequestItem(item.unique_id, item.searchQuery, response.url, response.status, response.message);
                    }
                },
                error: function(xhr, textStatus, errorThrown) { // jQuery .fail() equivalent
                    console.log(`Status check AJAX failed for ${item.unique_id} (${item.searchQuery}). Status: ${textStatus}, Error: ${errorThrown}. Removing from history.`);
                    removeDownloadFromHistory(item.unique_id);
                }
            });
        });
    };

    // Save download to user's storage - include status and message
    const saveDownload = (unique_id, searchQuery, url, status = 'pending', message = '') => {
        let userDownloads = JSON.parse(localStorage.getItem('userDownloads') || '[]');
        const existingIndex = userDownloads.findIndex(d => d.unique_id === unique_id);

        const newItem = { 
            unique_id, 
            searchQuery, 
            url, 
            status, 
            message: message || '', // Ensure message is not undefined
            timestamp: new Date().toISOString() 
        };

        if (existingIndex > -1) {
            userDownloads[existingIndex] = newItem;
        } else {
            userDownloads.push(newItem);
        }
        
        userDownloads.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
        localStorage.setItem('userDownloads', JSON.stringify(userDownloads));
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
        console.log('Download complete event:', data);
        if (pendingDownloads.has(data.unique_id)) {
            const searchQuery = pendingDownloads.get(data.unique_id);
            updateRequestItem(data.unique_id, searchQuery, data.url, 'completed');
            // saveDownload is called by updateRequestItem for 'completed'
        }
    });

    socket.on('download_failed', function(data) {
        console.log('Download failed event:', data);
        // data should contain unique_id, message, search_query, zip_url
        updateRequestItem(data.unique_id, data.search_query, data.zip_url, 'failed', data.message);
        notificationSystem.error('Download Failed', `${data.search_query || 'Item'}: ${data.message}`);
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
    const updateRequestItem = (requestId, searchQuery, url, status, message = '') => {
        console.log('Updating request item:', requestId, searchQuery, status, url, message);
        const existingItem = $(`#${requestId}`);
        
        if (!existingItem.length) {
            console.log('Item not found in DOM for update:', requestId);
            // If item doesn't exist, and it's a final state, maybe add it if it's from a socket event
            // For now, assume loadDownloadHistory creates the initial item.
            return; 
        }

        existingItem.find('.spinner-border').remove();
        let statusText = searchQuery || 'Download'; // Fallback if searchQuery is undefined
        let buttons = '';
        let statusClass = '';

        switch(status) {
            case 'completed':
                statusText = `${searchQuery} (<span style="color: green;">Completed</span>)`;
                statusClass = 'list-group-item-success';
                if (url) {
                    buttons = `<button class="btn btn-success btn-sm ms-2" onclick="startDownload('${url}', '${searchQuery}.zip', '${requestId}')">Download</button>`;
                }
                pendingDownloads.delete(requestId);
                saveDownload(requestId, searchQuery, url, 'completed', message); 
                break;
            case 'pending':
                statusText = `${searchQuery} (Pending)`;
                statusClass = 'list-group-item-info';
                existingItem.append(' <div class="spinner-border spinner-border-sm" role="status"></div>');
                pendingDownloads.set(requestId, searchQuery); // Ensure it's in pending map
                // saveDownload is typically called on initiation for 'pending'
                break;
            case 'failed':
                statusText = `${searchQuery} (<span style="color: red;">Failed</span>)`;
                if (message) {
                    statusText += ` <small class="text-muted">(${message})</small>`;
                }
                statusClass = 'list-group-item-danger';
                if (url) { // URL to the zip containing error.txt
                    buttons = `<button class="btn btn-warning btn-sm ms-2" onclick="startDownload('${url}', '${searchQuery}_error.zip', '${requestId}')">Error Log</button>`;
                }
                // Add a retry button that calls a global retry function
                buttons += ` <button class="btn btn-info btn-sm ms-2" onclick="handleRetry('${requestId}', '${searchQuery}')">Retry</button>`;
                pendingDownloads.delete(requestId);
                saveDownload(requestId, searchQuery, url, 'failed', message);
                break;
            case 'error': // e.g. status check failed
                 statusText = `${searchQuery} (<span style="color: orange;">Error</span>)`;
                 if (message) statusText += ` <small class="text-muted">(${message})</small>`;
                 statusClass = 'list-group-item-warning';
                 pendingDownloads.delete(requestId);
                 saveDownload(requestId, searchQuery, url, 'error', message);
                 break;
            default: // e.g. 'not_found' or other unexpected
                statusText = `${searchQuery} (<span style="color: grey;">${status || 'Unknown'}</span>)`;
                if (message) statusText += ` <small class="text-muted">(${message})</small>`;
                statusClass = 'list-group-item-light';
                pendingDownloads.delete(requestId);
                // removeDownloadFromHistory(requestId); // Or let user clear manually
                saveDownload(requestId, searchQuery, url, status, message);
                break;
        }

        existingItem.find('span:first').html(statusText);
        existingItem.removeClass('list-group-item-success list-group-item-info list-group-item-danger list-group-item-warning list-group-item-light').addClass(statusClass);
        
        // Remove old buttons before adding new ones
        existingItem.find('button').remove();
        if (buttons) {
            existingItem.append(buttons);
        }
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
        .done(function(responseData, textStatus, jqXHR) { // Renamed data to responseData for clarity
            console.log("Search POST .done() reached. HTTP Status:", jqXHR.status, "textStatus:", textStatus);
            console.log("Raw responseText from server:", jqXHR.responseText);
            console.log("jQuery parsed 'responseData' object:", responseData);

            let actualData = null;

            // Check if responseData is an array and the first element is the expected object
            if (Array.isArray(responseData) && responseData.length > 0 && 
                typeof responseData[0] === 'object' && responseData[0] !== null && 
                responseData[0].hasOwnProperty('status') && responseData[0].hasOwnProperty('unique_id')) {
                console.log("responseData is an array, using responseData[0] as actualData.");
                actualData = responseData[0];
            } else if (typeof responseData === 'object' && responseData !== null) { // Standard object response
                console.log("responseData is an object, using it as actualData.");
                actualData = responseData;
            }

            if (actualData && actualData.status === 'success' && actualData.unique_id) {
                console.log("Successfully processed: unique_id =", actualData.unique_id, "searchQuery =", searchQuery);
                pendingDownloads.set(actualData.unique_id, searchQuery);
                saveDownload(actualData.unique_id, searchQuery, null, 'pending');

                const requestItem = `<li id="${actualData.unique_id}" class="list-group-item list-group-item-info">
                    <span>${searchQuery} (Pending)</span>
                    <div class="spinner-border spinner-border-sm" role="status"></div>
                </li>`;
                $("#requests-list").prepend(requestItem);
                notificationSystem.success('Request Sent', `Download for "${searchQuery}" has been initiated.`);

            } else {
                let specificMessage = 'Server sent a 2xx response, but the data format was unexpected or incomplete.';
                if (actualData && actualData.message) { // If server sent a 2xx with its own error message in the processed data
                    specificMessage = actualData.message;
                } else if (Array.isArray(responseData)) {
                    specificMessage = `Server sent a 2xx response, but the expected object was not found in the received array. Array: ${JSON.stringify(responseData).substring(0,100)}...`;
                } else if (typeof responseData !== 'object' || responseData === null) {
                    specificMessage = 'Server sent a 2xx response, but the data was not valid JSON, was empty, or an unhandled structure.';
                } else if (!actualData || !actualData.status || !actualData.unique_id) {
                    specificMessage = 'Server sent a 2xx response, but "status" or "unique_id" was missing in the processed data.';
                }
                
                console.error('Problem in .done(): Unexpected data structure. Original Parsed Data:', responseData, 'Processed actualData:', actualData, 'HTTP Status:', jqXHR.status);
                notificationSystem.error('Search Error (Client)', specificMessage);
            }
        })
        .fail(function(jqXHR, textStatus, errorThrown) {
            console.error('Request failed. Status:', jqXHR.status, 'Response:', jqXHR.responseText, 'Error:', errorThrown);
            let message = 'Failed to start download. Please try again.'; // Ensure default message is always set
            
            if (jqXHR.responseJSON && jqXHR.responseJSON.message) {
                message = jqXHR.responseJSON.message;
            } else if (jqXHR.status === 429) {
                message = 'Too many requests. Please try again later.';
            } else if (jqXHR.status === 0) {
                message = 'Network error or server unreachable. Please check your connection.';
            } else if (jqXHR.responseText) { // Fallback to responseText if no JSON message
                // Try to parse as text, could be HTML error page or plain text
                // Avoid showing full HTML pages as notifications
                if (jqXHR.responseText.length < 200 && !jqXHR.responseText.trim().startsWith('<')) {
                    message = jqXHR.responseText;
                } else {
                    message = `Server returned status ${jqXHR.status}. Please check server logs.`;
                }
            }
            // If message is still the default and errorThrown has info, append it.
            else if (message === 'Failed to start download. Please try again.' && errorThrown) {
                message = `Failed to start download: ${errorThrown}`;
            }

            notificationSystem.error('Error', message);
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

    // Global function for retrying downloads
    window.handleRetry = function(uniqueId, searchQuery) {
        console.log("Retrying download for:", uniqueId, searchQuery);
        notificationSystem.info('Retrying...', `Preparing to retry download for ${searchQuery}.`);

        // 1. Remove the old item from UI and localStorage to avoid duplicate unique_ids if server reuses or if we want a fresh start
        removeDownloadFromHistory(uniqueId); // This also removes from pendingDownloads map

        // 2. Set the search query in the input field
        $("#search_query").val(searchQuery);
        // TODO: Potentially restore other form fields (audio_format, etc.) if they were specific to this download.
        // This might require storing them with the download item in localStorage.
        // For now, it will use current form values.

        // 3. Trigger the download initiation logic
        initiateDownload();
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
