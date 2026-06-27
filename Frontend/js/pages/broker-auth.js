// broker-auth.js - Intermediate Broker Authentication Controller
'use strict';

document.addEventListener('DOMContentLoaded', () => {
    const accessToken = localStorage.getItem('access_token');
    if (!accessToken) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
        window.location.replace('login.html');
        return;
    }

    const connectBtn = document.getElementById('btn-connect');
    if (connectBtn) {
        connectBtn.addEventListener('click', () => {
            window.location.replace('broker-connect.html');
        });
    }

    const setupBtn = document.getElementById('btn-setup');
    if (setupBtn) {
        setupBtn.addEventListener('click', () => {
            window.location.replace('broker-setup.html');
        });
    }

    const logoutBtn = document.getElementById('btn-logout');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            localStorage.removeItem('access_token');
            localStorage.removeItem('user');
            window.location.replace('login.html');
        });
    }
});
