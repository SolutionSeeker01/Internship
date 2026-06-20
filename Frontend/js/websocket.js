/* =============================================================
   websocket.js  –  WebSocket connection and message routing
   ============================================================= */

'use strict';

console.info("[WebSocket] Module loaded.");

const WS_URL             = `ws://${window.location.hostname}:8000/ws`;
const RECONNECT_DELAY_MS = 5_000;

/** @type {WebSocket|null} */
let socket = null;

/** @type {ReturnType<typeof setTimeout>|null} */
let reconnectTimer = null;

/* -------------------------------------------------------------
   MESSAGE HANDLERS
   ------------------------------------------------------------- */

/**
 * Handle a 'snapshot' message – bulk-populate every symbol at once.
 *
 * @param {Record<string, object>} data  – object keyed by symbol name
 */
function handleSnapshot(data) {
    for (const [token, marketData] of Object.entries(data)) {
        const symbol = marketData.symbol;
        if (!symbol) continue;
        
        latestMarketData.set(symbol, marketData);
        if (document.getElementById(`index-card-${symbol}`)) {
            updateIndexCard(symbol, marketData);
        } else if (document.getElementById(`stock-row-${symbol}`)) {
            updateStockRow(symbol, marketData);
        }
    }
    updateMarketStats();
}

/**
 * Handle an 'update' message – refresh only the affected symbol.
 * The `symbol` field is expected to be present inside `data`.
 *
 * @param {object} data  – single symbol's market data
 */
function handleUpdate(data) {
    const symbol = data.symbol;
    if (!symbol) {
        console.warn('[Dashboard] Update message missing symbol field:', data);
        return;
    }
    latestMarketData.set(symbol, data);

    if (document.getElementById(`index-card-${symbol}`)) {
        updateIndexCard(symbol, data);
    } else if (document.getElementById(`stock-row-${symbol}`)) {
        updateStockRow(symbol, data);
        updateMarketStats();
    }

    // Feed live updates to the historical candlestick chart (decoupled from DOM element check)
    if (selectedSymbol && symbol.trim().toUpperCase() === selectedSymbol.trim().toUpperCase()) {
        updateLiveCandle(data);
    }
}

/* -------------------------------------------------------------
   WEBSOCKET CONNECTION MANAGEMENT
   ------------------------------------------------------------- */

/**
 * Open a WebSocket connection and wire up all event handlers.
 */
function connectWebSocket() {
    if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }

    if (socket !== null) {
        socket.onclose = null;
        socket.close();
        socket = null;
    }

    console.info(`[Dashboard] Connecting to ${WS_URL} …`);
    updateConnectionStatus('disconnected');

    try {
        socket = new WebSocket(WS_URL);
    } catch (err) {
        console.error('[Dashboard] WebSocket constructor threw:', err);
        scheduleReconnect();
        return;
    }

    /* ---- onopen ---- */
    socket.onopen = () => {
        console.info('[Dashboard] WebSocket connected.');
        updateConnectionStatus('connected');
    };

    /* ---- onmessage ---- */
    socket.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);

            switch (message.type) {
                case 'snapshot':
                    handleSnapshot(message.data);
                    break;

                case 'update':
                    handleUpdate(message.data);
                    break;

                default:
                    console.warn('[Dashboard] Unknown message type:', message.type);
            }
        } catch (err) {
            console.error('[Dashboard] Failed to process message:', err, event.data);
        }
    };

    /* ---- onerror ---- */
    socket.onerror = (event) => {
        console.error('[Dashboard] WebSocket error:', event);
    };

    /* ---- onclose ---- */
    socket.onclose = (event) => {
        console.warn(
            `[Dashboard] WebSocket closed. code=${event.code} ` +
            `reason="${event.reason}". ` +
            `Reconnecting in ${RECONNECT_DELAY_MS / 1_000}s …`
        );
        updateConnectionStatus('disconnected');
        socket = null;
        scheduleReconnect();
    };
}

/**
 * Schedule a single reconnection attempt.
 */
function scheduleReconnect() {
    if (reconnectTimer !== null) return;
    reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connectWebSocket();
    }, RECONNECT_DELAY_MS);
}
