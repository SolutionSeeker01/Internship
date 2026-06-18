/* =============================================================
   app.js  –  Application Bootstrap and Wiring
   ============================================================= */

'use strict';

console.info("[App] Bootstrapping application...");

document.addEventListener('DOMContentLoaded', async () => {
    // Start WebSocket Connection
    connectWebSocket();
    
    // Start Header Clock
    updateHeaderClock();
    setInterval(updateHeaderClock, 1000);
    
    // Load Watchlist dynamically first
    await loadWatchlist();
    
    // Initialize Chart and Load Default Symbol Candles
    initializeChart();
    loadCandles(selectedSymbol);
    
    // Set up UI Event Listeners
    setupTimeframeSelection();
    
    // Navigation view selectors
    const btnDashboard = document.getElementById("nav-btn-dashboard");
    const btnInstruments = document.getElementById("nav-btn-instruments");
    
    if (btnDashboard) {
        btnDashboard.addEventListener("click", () => switchView("dashboard"));
    }
    if (btnInstruments) {
        btnInstruments.addEventListener("click", () => switchView("instruments"));
    }
    
    console.info("[App] Bootstrapped successfully.");
});
