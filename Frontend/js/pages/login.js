// Initialize event listeners on page load
document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('login-form');
    if (loginForm) {
        loginForm.addEventListener('submit', handleLogin);
    }

    const togglePasswordBtn = document.getElementById('btn-toggle-password');
    if (togglePasswordBtn) {
        togglePasswordBtn.addEventListener('click', togglePasswordVisibility);
    }

    const forgotPasswordLink = document.querySelector('.forgot-password');
    if (forgotPasswordLink) {
        forgotPasswordLink.addEventListener('click', (event) => {
            event.preventDefault();
            alert('Please contact your administrator to reset your password.');
        });
    }
});

// Password Visibility Toggle
function togglePasswordVisibility(e) {
    e.preventDefault();
    const passwordInput = document.getElementById('password');
    const eyeIcon = document.getElementById('eye-icon');
    if (!passwordInput || !eyeIcon) return;
    
    if (passwordInput.type === 'password') {
        passwordInput.type = 'text';
        // Switch icon to "eye-off"
        eyeIcon.innerHTML = `
            <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
            <line x1="1" y1="1" x2="23" y2="23"></line>
        `;
    } else {
        passwordInput.type = 'password';
        // Switch icon back to regular "eye"
        eyeIcon.innerHTML = `
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
            <circle cx="12" cy="12" r="3"></circle>
        `;
    }
}

// Login Handler
async function handleLogin(event) {
    event.preventDefault();
    
    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');
    const submitBtn = document.getElementById('btn-submit');
    const btnText = document.getElementById('btn-text');
    const errorBanner = document.getElementById('error-banner');
    
    const username = usernameInput.value.trim();
    const password = passwordInput.value;
    
    // Client-side Validation
    if (!username || !password) {
        showError("Validation Error", "Username and password cannot be empty.");
        return;
    }
    
    // Reset UI state
    errorBanner.style.display = 'none';
    submitBtn.disabled = true;
    btnText.textContent = "Logging in...";
    
    try {
        const response = await fetch('http://127.0.0.1:8000/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
        });
        
        if (response.ok) {
            const data = await response.json();
            
            // Store credentials
            localStorage.setItem('access_token', data.access_token);
            localStorage.setItem('user', JSON.stringify(data.user));
            
            // Redirect to bootstrap.html
            window.location.href = 'bootstrap.html';
        } else {
            // Handle HTTP error statuses
            if (response.status === 401) {
                showError("Invalid username or password.", "Please verify your credentials and try again.");
            } else {
                showError("Login failed", "An unexpected server error occurred.");
            }
        }
    } catch (error) {
        // Handle network failure or other exceptions
        showError("Unable to connect to server", "Please check your server connection and try again.");
        console.error("Login request failed:", error);
    } finally {
        // Restore button state if not redirected
        submitBtn.disabled = false;
        btnText.textContent = "Secure Login";
    }
}

function showError(title, description) {
    const errorBanner = document.getElementById('error-banner');
    const errorTitle = document.getElementById('error-title');
    const errorDesc = document.getElementById('error-desc');
    
    errorTitle.textContent = title;
    errorDesc.textContent = description;
    errorBanner.style.display = 'flex';
}
