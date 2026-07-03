// bootstrap.js - Client Routing and Bootstrap Onboarding Controller
'use strict';

document.addEventListener('DOMContentLoaded', async () => {
    const statusText = document.getElementById('status-text');
    const spinner = document.getElementById('spinner');
    const errorBox = document.getElementById('error-box');
    const retryBtn = document.getElementById('btn-retry');

    if (retryBtn) {
        retryBtn.addEventListener('click', () => {
            window.location.reload();
        });
    }

    function showError(message) {
        if (spinner) spinner.style.display = 'none';
        if (statusText) statusText.style.display = 'none';
        if (errorBox) {
            errorBox.textContent = message;
            errorBox.style.display = 'block';
        }
        if (retryBtn) retryBtn.style.display = 'inline-block';
    }

    // STEP 1: Read and validate access_token from localStorage
    const accessToken = localStorage.getItem('access_token');
    if (!accessToken) {
        // Token doesn't exist, redirect to login
        window.location.replace('login.html');
        return;
    }

    // STEP 2: Call the backend bootstrap API endpoint
    try {
        const response = await fetch(`${window.API_BASE_URL}/auth/bootstrap`, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${accessToken}`,
                'Content-Type': 'application/json'
            }
        });

        // STEP 4: Handle 401 Unauthorized response
        if (response.status === 401) {
            localStorage.removeItem('access_token');
            localStorage.removeItem('user');
            window.location.replace('login.html');
            return;
        }

        if (response.ok) {
            const data = await response.json();
            const state = data.state;

            // STEP 3: Route based on broker onboarding status state
            if (state === 'BROKER_SETUP_REQUIRED') {
                window.location.replace('broker-setup.html');
            } else if (state === 'BROKER_AUTH_REQUIRED') {
                window.location.replace('broker-auth.html');
            } else if (state === 'FULLY_READY') {
                // Read stored user profile details to route by authorization role
                const userString = localStorage.getItem('user');
                let user = null;
                try {
                    user = JSON.parse(userString);
                } catch (e) {
                    console.error('Failed to parse user details from local storage:', e);
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('user');
                    window.location.replace('login.html');
                    return;
                }

                if (user && user.role === 'CLIENT') {
                    window.location.replace('client-dashboard.html');
                } else {
                    // Default fallback/MASTER redirects to main dashboard
                    window.location.replace('dashboard.html');
                }
            } else {
                throw new Error(`Unknown bootstrap state: ${state}`);
            }
        } else {
            // Handle other HTTP status error codes
            throw new Error(`HTTP Error Status: ${response.status}`);
        }
    } catch (error) {
        // Check if error is likely a network/fetch connection drop
        if (error instanceof TypeError) {
            showError('Unable to connect to server');
        } else {
            showError('Failed to initialize application');
        }
        console.error('Bootstrap router failure:', error);
    }
});
