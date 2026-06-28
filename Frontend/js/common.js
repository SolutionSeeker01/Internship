/* =============================================================
   common.js  –  Shared frontend layouts controllers (Clock, Auth, etc)
   ============================================================= */

'use strict';

console.info("[Common] Module loaded.");

/**
 * Handle user logout logic.
 */
function handleLogout() {
    if (window.confirm("Are you sure you want to logout?")) {
        localStorage.removeItem("access_token");
        localStorage.removeItem("user");
        window.location.replace("login.html");
    }
}

/**
 * High-level layout checks and shared DOM initialization.
 */
document.addEventListener('DOMContentLoaded', () => {
    // 1. Navbar setup & active state tracking
    const path = window.location.pathname;
    const pageName = path.substring(path.lastIndexOf('/') + 1);

    const btnDashboard = document.getElementById("nav-btn-dashboard");
    const btnInstruments = document.getElementById("nav-btn-instruments");
    const btnUsers = document.getElementById("nav-btn-users");
    const btnLogout = document.getElementById("nav-btn-logout");

    // Apply active classes based on filename
    if (pageName === "dashboard.html" && btnDashboard) {
        btnDashboard.classList.add("active");
    } else if (pageName === "instrument-manager.html" && btnInstruments) {
        btnInstruments.classList.add("active");
    }

    // Set up standard listeners
    if (btnDashboard) {
        btnDashboard.addEventListener("click", () => {
            window.location.replace("dashboard.html");
        });
    }
    if (btnInstruments) {
        btnInstruments.addEventListener("click", () => {
            window.location.replace("instrument-manager.html");
        });
    }
    if (btnUsers) {
        btnUsers.addEventListener("click", () => {
            window.location.replace("user-management.html");
        });
    }
    if (btnLogout) {
        btnLogout.addEventListener("click", handleLogout);
    }

    // Check if current user is MASTER to display user management button
    const userStr = localStorage.getItem("user");
    if (userStr) {
        try {
            const userObj = JSON.parse(userStr);
            if (userObj && userObj.role === "MASTER" && btnUsers) {
                btnUsers.style.display = "inline-block";
            }
        } catch (e) {
            console.error("Failed to parse user details:", e);
        }
    }

    // 2. Synchronized Header Clock
    const clockEl = document.getElementById("header-clock");
    if (clockEl) {
        const updateClock = () => {
            const now = new Date();
            clockEl.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
        };
        updateClock();
        setInterval(updateClock, 1000);
    }
});
