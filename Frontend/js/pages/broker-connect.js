// broker-connect.js - Zerodha Authentication Redirection Controller
'use strict';

document.addEventListener('DOMContentLoaded', async () => {
    const statusText = document.getElementById('status-text');
    const spinner = document.getElementById('spinner');
    const errorBox = document.getElementById('error-box');
    const retryBtn = document.getElementById('btn-retry');

    // Attach retry button listener programmatically
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

    // 1. Verify access_token exists in localStorage
    const accessToken = localStorage.getItem('access_token');
    if (!accessToken) {
        // Redirect to login.html
        window.location.replace('login.html');
        return;
    }

    try {
        // 3. Immediately call backend connection API endpoint
        const response = await fetch('http://127.0.0.1:8000/auth/broker/connect', {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${accessToken}`,
                'Content-Type': 'application/json'
            }
        });

        // 4. Handle 401 Unauthorized response
        if (response.status === 401) {
            localStorage.removeItem('access_token');
            localStorage.removeItem('user');
            window.location.replace('login.html');
            return;
        }

        if (response.ok) {
            const data = await response.json();
            
            // 5. Frontend automatically redirects browser (with strengthened validation)
            if (data && typeof data.login_url === 'string' && data.login_url.trim()) {
                window.location.href = data.login_url;
                return;
            } else {
                throw new Error('Missing login URL in response');
            }
        } else {
            // Handle non-success response status
            throw new Error(`HTTP Error Status: ${response.status}`);
        }
    } catch (error) {
        // Network resilience check using instanceof TypeError
        if (error instanceof TypeError) {
            showError('Unable to connect to server');
        } else {
            showError('Failed to initiate broker connection');
        }
        // Safer error log that does not dump dynamic inputs/responses or sensitive properties
        console.error('Broker connect router failure occurred');
    }
});
