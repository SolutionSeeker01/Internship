/* =============================================================
   app.js  –  Application Bootstrap and Wiring
   ============================================================= */

'use strict';

console.info("[App] Bootstrapping application...");

document.addEventListener('DOMContentLoaded', () => {
    // Start WebSocket Connection
    connectWebSocket();
    
    // Start Header Clock
    updateHeaderClock();
    setInterval(updateHeaderClock, 1000);
    
    // Initialize Chart and Load Default Symbol Candles
    initializeChart();
    loadCandles(selectedSymbol);
    
    // Set up UI Event Listeners
    setupStockSelection();
    setupTimeframeSelection();
    
    console.info("[App] Bootstrapped successfully.");
});
