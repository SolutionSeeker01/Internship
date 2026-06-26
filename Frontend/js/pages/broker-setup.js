// broker-setup.js - Zerodha Onboarding Configuration Controller
'use strict';

// STEP 1: Verify access token on page load
document.addEventListener('DOMContentLoaded', () => {
    const accessToken = localStorage.getItem('access_token');
    if (!accessToken) {
        window.location.replace('login.html');
        return; // IMPROVEMENT 2
    }

    // IMPROVEMENT 1: Attach Event Listeners programmatically
    const setupForm = document.getElementById('setup-form');
    if (setupForm) {
        setupForm.addEventListener('submit', handleSetupSubmit);
    }

    const toggleKeyBtn = document.getElementById('btn-toggle-key');
    if (toggleKeyBtn) {
        toggleKeyBtn.addEventListener('click', () => {
            toggleFieldVisibility('api-key', 'eye-icon-key');
        });
    }

    const toggleSecretBtn = document.getElementById('btn-toggle-secret');
    if (toggleSecretBtn) {
        toggleSecretBtn.addEventListener('click', () => {
            toggleFieldVisibility('api-secret', 'eye-icon-secret');
        });
    }
});

// Password visibility toggle helper
function toggleFieldVisibility(fieldId, iconId) {
    const inputField = document.getElementById(fieldId);
    const eyeIcon = document.getElementById(iconId);
    if (!inputField || !eyeIcon) return;

    if (inputField.type === 'password') {
        inputField.type = 'text';
        // Switch to eye-off SVG icon
        eyeIcon.innerHTML = `
            <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
            <line x1="1" y1="1" x2="23" y2="23"></line>
        `;
    } else {
        inputField.type = 'password';
        // Switch back to regular eye SVG icon
        eyeIcon.innerHTML = `
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
            <circle cx="12" cy="12" r="3"></circle>
        `;
    }
}

// Form Submission Flow
async function handleSetupSubmit(event) {
    event.preventDefault();

    const apiKeyInput = document.getElementById('api-key');
    const apiSecretInput = document.getElementById('api-secret');
    const submitBtn = document.getElementById('btn-submit');
    const btnText = document.getElementById('btn-text');
    const errorBanner = document.getElementById('error-banner');
    const errorMessage = document.getElementById('error-message');
    const successBanner = document.getElementById('success-banner');

    const apiKey = apiKeyInput.value.trim();
    const apiSecret = apiSecretInput.value.trim();

    // Client-side Validation (reject empty/whitespace-only values)
    if (!apiKey || !apiSecret) {
        showError('API Key and API Secret cannot be empty or only spaces.');
        return;
    }

    // Clear previous banner displays
    errorBanner.style.display = 'none';
    successBanner.style.display = 'none';

    // Step 1: Disable button and show loading state
    submitBtn.disabled = true;
    btnText.textContent = 'Saving...';

    const accessToken = localStorage.getItem('access_token');
    if (!accessToken) {
        window.location.replace('login.html');
        return;
    }

    try {
        // Step 2: Send setup request to backend
        const response = await fetch('http://127.0.0.1:8000/auth/broker/setup', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${accessToken}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                api_key: apiKey,
                api_secret: apiSecret
            })
        });

        // Step 3: Handle 401 Unauthorized
        if (response.status === 401) {
            localStorage.removeItem('access_token');
            localStorage.removeItem('user');
            window.location.replace('login.html');
            return;
        }

        if (response.ok) {
            // Step 4: Show success message and redirect to bootstrap router
            successBanner.style.display = 'flex';
            setTimeout(() => {
                window.location.replace('bootstrap.html');
            }, 1000);
        } else {
            // Step 5: IMPROVEMENT 3 - Read and display backend detail error messages safely
            let details = 'Failed to save credentials.';
            try {
                const errorData = await response.json();
                details = errorData.detail || details;
            } catch (e) {
                console.error('Failed to parse error response:', e);
            }
            showError(details);
            submitBtn.disabled = false;
            btnText.textContent = 'Save & Continue';
        }
    } catch (error) {
        // Step 6: Handle network outage or disconnects
        showError('Unable to connect to server');
        submitBtn.disabled = false;
        btnText.textContent = 'Save & Continue';
        console.error('Broker setup submission failure:', error);
    }

    function showError(message) {
        errorMessage.textContent = message;
        errorBanner.style.display = 'flex';
        successBanner.style.display = 'none';
    }
}
