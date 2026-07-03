// broker-callback.js - Zerodha Authentication Callback Controller
'use strict';

document.addEventListener('DOMContentLoaded', async () => {
    const statusText = document.getElementById('status-text');
    const spinner = document.getElementById('spinner');
    const errorBox = document.getElementById('error-box');
    const successBanner = document.getElementById('success-banner');
    const retryBtn = document.getElementById('btn-retry');
    const setupBtn = document.getElementById('btn-setup');
    const recoveryActions = document.getElementById('recovery-actions');
    const loginBtn = document.getElementById('btn-login');

    // Bind action listeners programmatically
    if (loginBtn) {
        loginBtn.addEventListener('click', () => {
            window.location.replace('login.html');
        });
    }

    if (retryBtn) {
        retryBtn.addEventListener('click', () => {
            window.location.replace('broker-connect.html');
        });
    }

    if (setupBtn) {
        setupBtn.addEventListener('click', () => {
            window.location.replace('broker-setup.html');
        });
    }

    function showError(message) {
        if (spinner) spinner.style.display = 'none';
        if (statusText) statusText.style.display = 'none';
        if (successBanner) successBanner.style.display = 'none';
        if (errorBox) {
            errorBox.textContent = message;
            errorBox.style.display = 'block';
        }
        if (loginBtn) loginBtn.style.display = 'inline-block';
        if (recoveryActions) recoveryActions.style.display = 'flex';
    }

    // 2. Read access_token from localStorage
    const accessToken = localStorage.getItem('access_token');
    if (!accessToken) {
        window.location.replace('login.html');
        return;
    }

    // 1. Extract request_token from URL query parameters
    const params = new URLSearchParams(window.location.search);
    const requestToken = params.get('request_token');

    // Query Parameter Validation (immediate type and whitespace check)
    if (!requestToken || !requestToken.trim()) {
        showError('Invalid callback response received');
        return;
    }

    try {
        // 3. Call backend endpoint to post authorization callback
        const response = await fetch(`${window.API_BASE_URL}/auth/broker/callback`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${accessToken}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                request_token: requestToken.trim()
            })
        });

        // 401 Unauthorized handling
        if (response.status === 401) {
            localStorage.removeItem('access_token');
            localStorage.removeItem('user');
            window.location.replace('login.html');
            return;
        }

        if (response.ok) {
            // 5. On success, show confirmation banner and redirect to bootstrap router
            if (spinner) spinner.style.display = 'none';
            if (statusText) statusText.style.display = 'none';
            if (successBanner) successBanner.style.display = 'flex';

            setTimeout(() => {
                window.location.replace('bootstrap.html');
            }, 1000);
        } else {
            // Handle HTTP status errors gracefully
            let detailMessage = 'Failed to complete broker authentication';
            try {
                const errorData = await response.json();
                if (errorData && typeof errorData.detail === 'string' && errorData.detail.trim()) {
                    detailMessage = errorData.detail;
                }
            } catch (e) {
                // Ignore error payload parsing issues, default to fallback string
            }
            showError(detailMessage);
        }
    } catch (error) {
        // Network resilience check using instanceof TypeError
        if (error instanceof TypeError) {
            showError('Unable to connect to server');
        } else {
            showError('Failed to complete broker authentication');
        }
        // Secure logging to prevent credential exposures
        console.error('Broker callback process failure occurred');
    }
});
