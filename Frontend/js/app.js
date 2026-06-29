/* =============================================================
   app.js  –  Application Bootstrap and Wiring
   ============================================================= */

'use strict';

console.info("[App] Bootstrapping application...");

document.addEventListener('DOMContentLoaded', async () => {
    // 1. Navigation view selectors (register first so UI navigation always works)
    const btnDashboard = document.getElementById("nav-btn-dashboard");
    const btnInstruments = document.getElementById("nav-btn-instruments");
    const btnUsers = document.getElementById("nav-btn-users");
    
    // Check if current user is MASTER to display user management button
    const userStr = localStorage.getItem("user");
    if (userStr) {
        try {
            const userObj = JSON.parse(userStr);
            if (userObj && userObj.role === "MASTER" && btnUsers) {
                btnUsers.style.display = "inline-block";
            }
        } catch (e) {
            console.error("Failed to parse user profile details:", e);
        }
    }



    // 2. Start WebSocket Connection
    try {
        connectWebSocket();
    } catch (e) {
        console.error("Failed to connect WebSocket:", e);
    }
    
    
    
    // 5. Initialize Chart and Load Default Symbol Candles
    try {
        initializeChart();
        if (typeof selectedSymbol !== "undefined" && selectedSymbol) {
            loadCandles(selectedSymbol);
        }
    } catch (e) {
        console.error("Failed to initialize chart:", e);
    }
    
    // 6. Set up UI Event Listeners
    try {
        setupTimeframeSelection();
    } catch (e) {
        console.error("Failed to setup timeframe selection:", e);
    }
    
    console.info("[App] Bootstrapped successfully.");
});
