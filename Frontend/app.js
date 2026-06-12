/* =============================================================
   app.js  –  Real-Time Market Dashboard WebSocket Client
   ============================================================= */

'use strict';

/* -------------------------------------------------------------
   CONFIGURATION
   ------------------------------------------------------------- */
// Dynamically derive the WebSocket URL based on the hostname of the page.
// This allows other devices (like phones/tablets) on the same local network
// to connect automatically to the server using the laptop's network IP (e.g. 192.168.x.x),
// while still resolving to 'localhost' when accessing locally.
const WS_URL             = `ws://${window.location.hostname}:8000/ws`;
const RECONNECT_DELAY_MS = 5_000;

const INDICES = new Set(['NIFTY50', 'BANKNIFTY', 'SENSEX']);

/* -------------------------------------------------------------
   STATE
   ------------------------------------------------------------- */
/** @type {WebSocket|null} */
let socket = null;

/** @type {ReturnType<typeof setTimeout>|null} */
let reconnectTimer = null;

/**
 * Tracks the last known LTP for every symbol so we can determine
 * whether a new tick is higher or lower (for flash animations).
 * @type {Map<string, number>}
 */
const previousLtp = new Map();

/* -------------------------------------------------------------
   FORMATTING HELPERS
   ------------------------------------------------------------- */

/**
 * Format a numeric price to exactly 2 decimal places.
 * Returns '—' for null / undefined / NaN values.
 *
 * @param {number|null|undefined} value
 * @returns {string}
 */
function formatPrice(value) {
    if (value == null || isNaN(value)) return '\u2014';
    return Number(value).toFixed(2);
}

/**
 * Format volume with locale-aware thousands separators.
 * Returns '—' for null / undefined / NaN values.
 *
 * @param {number|null|undefined} value
 * @returns {string}
 */
function formatVolume(value) {
    if (value == null || isNaN(value)) return '\u2014';
    return Number(value).toLocaleString();
}

/**
 * Format a change percentage with an explicit sign prefix.
 * Returns '—' for null / undefined / NaN values.
 *
 * @param {number|null|undefined} value
 * @returns {string}
 */
function formatChange(value) {
    if (value == null || isNaN(value)) return '\u2014';
    const num  = Number(value);
    const sign = num > 0 ? '+' : '';   // negative sign comes from toFixed itself
    return `${sign}${num.toFixed(2)}%`;
}

/* -------------------------------------------------------------
   DOM HELPERS
   ------------------------------------------------------------- */

/**
 * Safely retrieve an element by ID.
 * Logs a warning once if the element is not found so we never
 * throw on a missing element in production.
 *
 * @param {string} id
 * @returns {HTMLElement|null}
 */
const _missingIds = new Set();
function getEl(id) {
    const el = document.getElementById(id);
    if (!el && !_missingIds.has(id)) {
        console.warn(`[Dashboard] Element not found: #${id}`);
        _missingIds.add(id);
    }
    return el;
}

/**
 * Apply the correct price-direction CSS class to an element.
 * Removes all direction classes before adding the new one.
 *
 * @param {HTMLElement} el
 * @param {number}      changeValue  – raw change % as a number
 */
function applyChangeClass(el, changeValue) {
    el.classList.remove('positive', 'negative', 'neutral');
    if      (changeValue > 0) el.classList.add('positive');
    else if (changeValue < 0) el.classList.add('negative');
    else                      el.classList.add('neutral');
}

/**
 * Trigger a one-shot flash animation on an element.
 * The class is removed as soon as animationend fires so the
 * animation can retrigger on the very next tick.
 *
 * @param {HTMLElement}           el
 * @param {'flash-up'|'flash-down'} cls
 */
function triggerFlash(el, cls) {
    // Remove both classes first …
    el.classList.remove('flash-up', 'flash-down');
    // … then force a reflow so the browser sees the removal before
    // we re-add the class (otherwise the CSS animation won't replay).
    void el.offsetWidth;
    el.classList.add(cls);
    el.addEventListener('animationend', () => el.classList.remove(cls), { once: true });
}

/* -------------------------------------------------------------
   CONNECTION STATUS
   ------------------------------------------------------------- */

/**
 * Update the header status dot and label text.
 *
 * @param {'connected'|'disconnected'} status
 */
function updateConnectionStatus(status) {
    const dot  = getEl('connection-status-dot');
    const text = getEl('connection-status-text');
    const isConnected = status === 'connected';

    if (dot) {
        dot.classList.toggle('connected',    isConnected);
        dot.classList.toggle('disconnected', !isConnected);
    }

    if (text) {
        text.textContent = isConnected ? 'Connected' : 'Disconnected';
    }
}

/* -------------------------------------------------------------
   INDEX CARD UPDATER
   ------------------------------------------------------------- */

/**
 * Update a single index card with fresh market data.
 *
 * @param {string} symbol  – e.g. 'NIFTY50'
 * @param {object} data    – market data fields from the server
 */
function updateIndexCard(symbol, data) {
    const ltpEl    = getEl(`index-ltp-${symbol}`);
    const changeEl = getEl(`index-change-${symbol}`);

    const ltp    = data.ltp    != null ? Number(data.ltp)    : null;
    const change = data.change != null ? Number(data.change) : null;

    if (ltpEl) {
        const prev = previousLtp.get(symbol);
        if (prev != null && ltp != null) {
            if      (ltp > prev) triggerFlash(ltpEl, 'flash-up');
            else if (ltp < prev) triggerFlash(ltpEl, 'flash-down');
        }
        ltpEl.textContent = formatPrice(ltp);
    }

    if (changeEl) {
        changeEl.textContent = formatChange(change);
        if (change != null) applyChangeClass(changeEl, change);
    }

    // Persist latest LTP for direction detection on the next tick
    if (ltp != null) previousLtp.set(symbol, ltp);
}

/* -------------------------------------------------------------
   STOCK ROW UPDATER
   ------------------------------------------------------------- */

/**
 * Update a single stock table row with fresh market data.
 *
 * @param {string} symbol  – e.g. 'RELIANCE'
 * @param {object} data    – market data fields from the server
 */
function updateStockRow(symbol, data) {
    const ltpEl    = getEl(`stock-ltp-${symbol}`);
    const changeEl = getEl(`stock-change-${symbol}`);
    const bidEl    = getEl(`stock-bid-${symbol}`);
    const askEl    = getEl(`stock-ask-${symbol}`);
    const volEl    = getEl(`stock-volume-${symbol}`);
    const openEl   = getEl(`stock-open-${symbol}`);
    const closeEl  = getEl(`stock-close-${symbol}`);

    const ltp    = data.ltp    != null ? Number(data.ltp)    : null;
    const change = data.change != null ? Number(data.change) : null;

    if (ltpEl) {
        const prev = previousLtp.get(symbol);
        if (prev != null && ltp != null) {
            if      (ltp > prev) triggerFlash(ltpEl, 'flash-up');
            else if (ltp < prev) triggerFlash(ltpEl, 'flash-down');
        }
        ltpEl.textContent = formatPrice(ltp);
    }

    if (changeEl) {
        changeEl.textContent = formatChange(change);
        if (change != null) applyChangeClass(changeEl, change);
    }

    if (bidEl)   bidEl.textContent   = formatPrice(data.bid);
    if (askEl)   askEl.textContent   = formatPrice(data.ask);
    if (volEl)   volEl.textContent   = formatVolume(data.volume);
    if (openEl)  openEl.textContent  = formatPrice(data.open);
    if (closeEl) closeEl.textContent = formatPrice(data.close);

    if (ltp != null) previousLtp.set(symbol, ltp);
}

/* -------------------------------------------------------------
   MESSAGE HANDLERS
   ------------------------------------------------------------- */

/**
 * Handle a 'snapshot' message – bulk-populate every symbol at once.
 *
 * @param {Record<string, object>} data  – object keyed by symbol name
 */
function handleSnapshot(data) {
    for (const [symbol, marketData] of Object.entries(data)) {
        console.log("Snapshot symbol:", symbol);
        if (INDICES.has(symbol)) {
            updateIndexCard(symbol, marketData);
        } else {
            updateStockRow(symbol, marketData);
        }
    }
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

    console.log("Update symbol:", symbol);
    if (INDICES.has(symbol)) {
        updateIndexCard(symbol, data);
    } else {
        updateStockRow(symbol, data);
    }
}

/* -------------------------------------------------------------
   WEBSOCKET
   ------------------------------------------------------------- */

/**
 * Open a WebSocket connection and wire up all event handlers.
 * Safe to call while a connection already exists – the old socket
 * is closed before creating a new one.
 */
function connectWebSocket() {
    // Cancel any pending reconnect timer
    if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }

    // Close any existing socket cleanly, suppressing its onclose
    // handler so we don't schedule a double reconnect.
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
        // The constructor itself can throw for invalid URLs
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
            // A malformed / non-JSON frame must never crash the client
            console.error('[Dashboard] Failed to process message:', err, event.data);
        }
    };

    /* ---- onerror ---- */
    socket.onerror = (event) => {
        // onerror is always followed by onclose in browsers, so we
        // only log here and let onclose handle the reconnect logic.
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
 * Schedule a single reconnection attempt after RECONNECT_DELAY_MS.
 * Guards against multiple concurrent timers.
 */
function scheduleReconnect() {
    if (reconnectTimer !== null) return;   // already scheduled
    reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connectWebSocket();
    }, RECONNECT_DELAY_MS);
}

/* -------------------------------------------------------------
   ENTRY POINT
   ------------------------------------------------------------- */
document.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();
});
