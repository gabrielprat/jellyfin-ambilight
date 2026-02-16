// ==UserScript==
// @name         Jellyfin Ambilight UI
// @namespace    https://github.com/yourusername/jellyfin-ambilight
// @version      1.2
// @description  Adds "Extract Ambilight" button to Jellyfin video detail pages
// @author       Your Name
// @match        https://*/web/*
// @match        http://*/web/*
// @icon         data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==
// @grant        none
// @run-at       document-end
// ==/UserScript==

(function() {
    'use strict';

    console.log('[Ambilight] Userscript loaded v1.2 (aggressive init)');

    let currentItemId = null;
    let statusCheckInterval = null;
    let buttonCheckInterval = null;

    /**
     * Check if ambilight data exists for the current item
     */
    async function checkAmbilightStatus(itemId) {
        try {
            console.log('[Ambilight] Checking status for item:', itemId);
            
            // Build the full URL
            const baseUrl = window.location.origin;
            const url = `${baseUrl}/Ambilight/Status/${itemId}`;
            console.log('[Ambilight] API URL:', url);
            
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include'
            });

            console.log('[Ambilight] Status response:', response.status);
            
            if (response.ok) {
                const data = await response.json();
                console.log('[Ambilight] Status data:', data);
                return data;
            } else {
                const errorText = await response.text();
                console.error('[Ambilight] Status request failed:', response.status, response.statusText);
                console.error('[Ambilight] Error details:', errorText);
                
                // Try to parse error JSON
                try {
                    const errorJson = JSON.parse(errorText);
                    console.error('[Ambilight] Error message:', errorJson.error);
                    if (errorJson.stackTrace) {
                        console.error('[Ambilight] Stack trace:', errorJson.stackTrace);
                    }
                } catch (e) {
                    // Not JSON, already logged as text
                }
            }
        } catch (error) {
            console.error('[Ambilight] Error checking status:', error);
        }
        return null;
    }

    /**
     * Trigger ambilight extraction for an item
     */
    async function triggerExtraction(itemId) {
        try {
            console.log('[Ambilight] Triggering extraction for:', itemId);
            
            if (typeof Dashboard !== 'undefined' && Dashboard.showLoadingMsg) {
                Dashboard.showLoadingMsg();
            }

            const baseUrl = window.location.origin;
            const url = `${baseUrl}/Ambilight/Extract/${itemId}`;
            
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include'
            });

            if (typeof Dashboard !== 'undefined' && Dashboard.hideLoadingMsg) {
                Dashboard.hideLoadingMsg();
            }

            console.log('[Ambilight] Extract response:', response.status);

            if (response.ok) {
                const result = await response.json();
                console.log('[Ambilight] Extract result:', result);
                alert(result.Message || 'Extraction started in background');

                // Start polling for completion
                startStatusPolling(itemId);
            } else {
                throw new Error(`Failed to start extraction: ${response.status}`);
            }
        } catch (error) {
            if (typeof Dashboard !== 'undefined' && Dashboard.hideLoadingMsg) {
                Dashboard.hideLoadingMsg();
            }
            console.error('[Ambilight] Error triggering extraction:', error);
            alert('Failed to start extraction: ' + error.message);
        }
    }

    /**
     * Poll extraction status
     */
    function startStatusPolling(itemId) {
        if (statusCheckInterval) {
            clearInterval(statusCheckInterval);
        }

        let attempts = 0;
        const maxAttempts = 60; // 5 minutes max

        statusCheckInterval = setInterval(async () => {
            attempts++;
            const status = await checkAmbilightStatus(itemId);

            if (status && status.HasBinary) {
                clearInterval(statusCheckInterval);
                statusCheckInterval = null;

                require(['toast'], function(toast) {
                    toast('Ambilight extraction completed!');
                });

                // Refresh the button
                addAmbilightButton(itemId);
            } else if (attempts >= maxAttempts) {
                clearInterval(statusCheckInterval);
                statusCheckInterval = null;
            }
        }, 5000); // Check every 5 seconds
    }

    /**
     * Add Ambilight button to the detail page
     */
    async function addAmbilightButton(itemId) {
        console.log('[Ambilight] === Attempting to add button for item:', itemId);

        // Debug: log all potential button containers
        console.log('[Ambilight] Looking for button containers...');
        console.log('[Ambilight] .itemDetailButtons:', document.querySelectorAll('.itemDetailButtons').length);
        console.log('[Ambilight] .detailButtons:', document.querySelectorAll('.detailButtons').length);
        console.log('[Ambilight] .mainDetailButtons:', document.querySelectorAll('.mainDetailButtons').length);
        console.log('[Ambilight] button.btnPlay:', document.querySelectorAll('button.btnPlay').length);
        console.log('[Ambilight] button.btnResume:', document.querySelectorAll('button.btnResume').length);

        // Check current status
        const status = await checkAmbilightStatus(itemId);
        if (!status) {
            console.warn('[Ambilight] Could not get status for item');
            return false;
        }

        // Try multiple selectors for the button container
        const selectors = [
            '.itemDetailButtons',
            '.detailButtons', 
            '.mainDetailButtons',
            'button.btnPlay',
            'button.btnResume',
            'button[data-action="resume"]',
            'button[data-action="play"]'
        ];

        let buttonContainer = null;
        for (const selector of selectors) {
            const elem = document.querySelector(selector);
            if (elem) {
                // If it's a button itself, get its parent container
                if (elem.tagName === 'BUTTON') {
                    buttonContainer = elem.parentElement;
                } else {
                    buttonContainer = elem;
                }
                console.log('[Ambilight] ✓ Found button container via:', selector, buttonContainer);
                break;
            }
        }

        if (!buttonContainer) {
            console.error('[Ambilight] ✗ Button container not found! Dumping page structure:');
            console.log('[Ambilight] Body classes:', document.body.className);
            console.log('[Ambilight] Main content:', document.querySelector('.mainAnimatedPages, .page'));
            return false;
        }

        // Remove existing button if present
        const existingButton = document.getElementById('ambilightExtractButton');
        if (existingButton) {
            existingButton.remove();
        }

        // Create button
        const button = document.createElement('button');
        button.id = 'ambilightExtractButton';
        button.setAttribute('is', 'emby-button');
        button.className = 'button-flat btnPlay detailButton emby-button';

        if (status.HasBinary) {
            // Already extracted - show status
            button.innerHTML = `
                <span class="material-icons" aria-hidden="true" style="font-size: 2em; color: #4ade80;">check_circle</span>
                <span style="margin-left: 0.5em;">Ambilight Ready</span>
            `;
            button.style.opacity = '0.7';
            button.disabled = true;
            button.title = `Ambilight data extracted (${(status.BinarySize / 1024 / 1024).toFixed(2)} MB)`;
        } else {
            // Not extracted - show rainbow button
            button.innerHTML = `
                <span class="material-icons rainbow-icon" aria-hidden="true" style="font-size: 2em;">blur_on</span>
                <span style="margin-left: 0.5em;">Extract Ambilight</span>
            `;
            button.title = 'Extract ambilight data for this video';

            button.addEventListener('click', async (e) => {
                e.preventDefault();
                button.disabled = true;
                button.innerHTML = `
                    <span class="material-icons rotating" aria-hidden="true" style="font-size: 2em;">sync</span>
                    <span style="margin-left: 0.5em;">Extracting...</span>
                `;
                await triggerExtraction(itemId);
            });
        }

        // Add button to container
        buttonContainer.appendChild(button);
        console.log('[Ambilight] Button successfully added to page');
        return true;
    }

    /**
     * Get item ID from URL (handles hash-based routing)
     */
    function getItemIdFromUrl() {
        // Jellyfin uses hash-based routing: #/details?id=...
        const hash = window.location.hash;
        
        if (!hash || !hash.includes('?')) {
            return null;
        }
        
        // Extract query string from hash
        const queryString = hash.split('?')[1];
        const params = new URLSearchParams(queryString);
        return params.get('id');
    }

    /**
     * Initialize when viewing a video detail page
     */
    function initializeForDetailPage() {
        console.log('[Ambilight] === initializeForDetailPage called ===');
        console.log('[Ambilight] Current URL:', window.location.href);
        console.log('[Ambilight] Hash:', window.location.hash);
        
        // Clear any existing interval
        if (buttonCheckInterval) {
            clearInterval(buttonCheckInterval);
            buttonCheckInterval = null;
        }

        // Get current item from page (handle hash-based routing)
        const itemId = getItemIdFromUrl();

        console.log('[Ambilight] Item ID from URL:', itemId);

        if (!itemId) {
            console.log('[Ambilight] No item ID in URL, skipping');
            return;
        }

        if (itemId === currentItemId) {
            console.log('[Ambilight] Same item as before, skipping');
            return;
        }

        currentItemId = itemId;
        console.log('[Ambilight] ✓ New item detected:', itemId);

        // Wait for ApiClient to be available
        if (typeof ApiClient === 'undefined') {
            console.log('[Ambilight] ApiClient not ready, waiting...');
            setTimeout(initializeForDetailPage, 500);
            return;
        }

        console.log('[Ambilight] ApiClient is available, fetching item info...');

        // Check if this is a video item (Movie or Episode)
        ApiClient.getItem(ApiClient.getCurrentUserId(), itemId).then(item => {
            console.log('[Ambilight] Item fetched:', item.Name, 'Type:', item.Type);
            
            if (item && (item.Type === 'Movie' || item.Type === 'Episode')) {
                console.log('[Ambilight] ✓ Video detail page confirmed:', item.Name, item.Type);

                // Try to add button, retry if it fails (page might still be loading)
                let attempts = 0;
                const maxAttempts = 20;

                buttonCheckInterval = setInterval(async () => {
                    attempts++;
                    console.log('[Ambilight] Attempt', attempts, 'to add button');
                    
                    try {
                        const success = await addAmbilightButton(itemId);

                        if (success || attempts >= maxAttempts) {
                            clearInterval(buttonCheckInterval);
                            buttonCheckInterval = null;

                            if (success) {
                                console.log('[Ambilight] ✓ Button added successfully!');
                            } else {
                                console.error('[Ambilight] ✗ Failed to add button after', attempts, 'attempts');
                            }
                        }
                    } catch (error) {
                        console.error('[Ambilight] Error adding button:', error);
                        clearInterval(buttonCheckInterval);
                        buttonCheckInterval = null;
                    }
                }, 500);
            } else {
                console.log('[Ambilight] Not a video item, type is:', item ? item.Type : 'unknown');
            }
        }).catch(err => {
            console.error('[Ambilight] Error fetching item:', err);
        });
    }

    // Add rainbow gradient and animation styles
    const style = document.createElement('style');
    style.textContent = `
        @keyframes ambilightRotate {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        @keyframes rainbowGlow {
            0% { filter: hue-rotate(0deg) brightness(1.2); }
            25% { filter: hue-rotate(90deg) brightness(1.3); }
            50% { filter: hue-rotate(180deg) brightness(1.2); }
            75% { filter: hue-rotate(270deg) brightness(1.3); }
            100% { filter: hue-rotate(360deg) brightness(1.2); }
        }
        .rotating {
            animation: ambilightRotate 1s linear infinite;
            display: inline-block;
        }
        .rainbow-icon {
            background: linear-gradient(135deg,
                #FF0080 0%,
                #FF8C00 20%,
                #FFD700 40%,
                #00FF00 60%,
                #00CED1 80%,
                #9370DB 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            animation: rainbowGlow 3s ease-in-out infinite;
            font-weight: bold;
        }
    `;
    document.head.appendChild(style);

    // Aggressive initialization - check every second
    function startMonitoring() {
        setInterval(() => {
            const hash = window.location.hash;
            if (hash.includes('/details?id=')) {
                const queryString = hash.split('?')[1];
                const params = new URLSearchParams(queryString);
                const itemId = params.get('id');
                
                // Only initialize if not already done for this item
                if (itemId && itemId !== currentItemId) {
                    console.log('[Ambilight] Detected new detail page:', itemId);
                    initializeForDetailPage();
                }
            }
        }, 1000); // Check every second
    }

    // Listen for page changes
    document.addEventListener('viewshow', function() {
        console.log('[Ambilight] viewshow event');
        setTimeout(initializeForDetailPage, 100);
    });

    // Watch for hash changes (SPA navigation)
    window.addEventListener('hashchange', function() {
        console.log('[Ambilight] Hash changed to:', window.location.hash);
        setTimeout(initializeForDetailPage, 100);
    });

    // Initial load
    console.log('[Ambilight] Starting initialization...');
    setTimeout(initializeForDetailPage, 1000);
    setTimeout(initializeForDetailPage, 3000); // Try again after 3 seconds
    
    // Start monitoring
    startMonitoring();

    console.log('[Ambilight] Userscript initialized');
})();
