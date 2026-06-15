/* =============================================================
   app.js  –  Real-Time Market Dashboard WebSocket Client
   ============================================================= */

'use strict';

/* -------------------------------------------------------------
   CONFIGURATION
   ------------------------------------------------------------- */
const WS_URL             = `ws://${window.location.hostname}:8000/ws`;
const RECONNECT_DELAY_MS = 5_000;

const INDICES = new Set(['NIFTY50', 'BANKNIFTY', 'SENSEX']);
const TOTAL_STOCKS_COUNT = 8; // Watchlist stock count

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

/**
 * Tracks the current change % for all active stocks to compute breadth
 * and leader parameters.
 * @type {Map<string, number>}
 */
const currentChanges = new Map();

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
 * Format volume with locale-aware thousands separators (e.g. Millions shorthand or commas).
 * This formats values exactly like the reference image (e.g., shorthand like 1.24M, 780K).
 *
 * @param {number|null|undefined} value
 * @returns {string}
 */
function formatVolume(value) {
    if (value == null || isNaN(value)) return '\u2014';
    const num = Number(value);
    
    // Formatting to Million / Thousand shorthand as seen on Bloomberg/TradingView
    if (num >= 1_000_000) {
        return `${(num / 1_000_000).toFixed(2)}M`;
    } else if (num >= 1_000) {
        return `${(num / 1_000).toFixed(0)}K`;
    }
    return num.toString();
}

/**
 * Format a change percentage with directional arrow prefixes.
 * Returns '—' for null / undefined / NaN values.
 *
 * @param {number|null|undefined} value
 * @returns {string}
 */
function formatChange(value) {
    if (value == null || isNaN(value)) return '\u2014';
    const num = Number(value);
    const sign = num > 0 ? '+' : '';
    const arrow = num > 0 ? '▲ ' : num < 0 ? '▼ ' : '';
    return `${arrow}${sign}${num.toFixed(2)}%`;
}

/* -------------------------------------------------------------
   DOM HELPERS
   ------------------------------------------------------------- */

/**
 * Safely retrieve an element by ID.
 * Logs a warning once if the element is not found.
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
 *
 * @param {HTMLElement}           el
 * @param {'flash-up'|'flash-down'} cls
 */
function triggerFlash(el, cls) {
    el.classList.remove('flash-up', 'flash-down');
    void el.offsetWidth; // Force reflow
    el.classList.add(cls);
    el.addEventListener('animationend', () => el.classList.remove(cls), { once: true });
}

/* -------------------------------------------------------------
   MARKET STATISTICS / BREADTH & LEADER
   ------------------------------------------------------------- */

/**
 * Updates the footer with dynamic metrics on advances, declines,
 * unchanged stocks, and the timestamp of the last tick payload.
 */
function updateMarketStats() {
    let advances = 0;
    let declines = 0;
    let unchanged = 0;

    for (const [symbol, change] of currentChanges.entries()) {
        if (INDICES.has(symbol)) continue;
        if (change > 0)       advances++;
        else if (change < 0)  declines++;
        else                  unchanged++;
    }

    // Include stocks that haven't received ticks yet as unchanged
    const remaining = Math.max(0, TOTAL_STOCKS_COUNT - currentChanges.size);
    unchanged += remaining;

    const advEl = getEl('breadth-advances');
    const decEl = getEl('breadth-declines');
    const uncEl = getEl('breadth-unchanged');

    if (advEl) advEl.textContent = advances;
    if (decEl) decEl.textContent = declines;
    if (uncEl) uncEl.textContent = unchanged;

    const timeEl = getEl('last-updated-time');
    if (timeEl) {
        const now = new Date();
        timeEl.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
    }
}

/**
 * Identifies the stock with the highest positive change percentage
 * and applies leader row formatting and filled gold star logic.
 */
function updateLeaderHighlight() {
    let maxChange = -Infinity;
    let leaderSymbol = null;

    for (const [symbol, change] of currentChanges.entries()) {
        if (change > 0 && change > maxChange) {
            maxChange = change;
            leaderSymbol = symbol;
        }
    }

    // Reset leader styles, badges, and stars for all rows
    document.querySelectorAll('.stock-row').forEach(row => {
        row.classList.remove('leader-row');
        const badge = row.querySelector('.leader-badge');
        if (badge) {
            badge.remove();
        }
        const star = row.querySelector('.star-icon');
        if (star) {
            star.textContent = '☆';
            star.classList.remove('star-active');
        }
    });

    // Apply leader styles to the top stock row
    if (leaderSymbol) {
        const row = getEl(`stock-row-${leaderSymbol}`);
        if (row) {
            row.classList.add('leader-row');
            const star = row.querySelector('.star-icon');
            if (star) {
                star.textContent = '★';
                star.classList.add('star-active');
            }
            const symbolCell = row.querySelector('.stock-symbol');
            if (symbolCell && !symbolCell.querySelector('.leader-badge')) {
                const badge = document.createElement('span');
                badge.className = 'leader-badge';
                badge.textContent = 'LEADER';
                symbolCell.appendChild(badge);
            }
        }
    }
}

/* -------------------------------------------------------------
   CONNECTION STATUS & CLOCK
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
        text.textContent = isConnected ? 'LIVE' : 'DISCONNECTED';
    }
}

/**
 * Keeps the header clock updated with local system time.
 */
function updateHeaderClock() {
    const clockEl = getEl('header-clock');
    if (clockEl) {
        const now = new Date();
        clockEl.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
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
    const cardEl   = getEl(`index-card-${symbol}`);

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
        if (change != null) {
            applyChangeClass(changeEl, change);
            if (cardEl) {
                cardEl.classList.remove('card-positive', 'card-negative', 'card-neutral');
                if      (change > 0) cardEl.classList.add('card-positive');
                else if (change < 0) cardEl.classList.add('card-negative');
                else                 cardEl.classList.add('card-neutral');
            }
        }
    }

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
        if (change != null) {
            applyChangeClass(changeEl, change);
            currentChanges.set(symbol, change);
        }
    }

    if (bidEl)   bidEl.textContent   = data.bid != null && !isNaN(data.bid) ? formatPrice(data.bid) : "0";
    if (askEl)   askEl.textContent   = data.ask != null && !isNaN(data.ask) ? formatPrice(data.ask) : "0";
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
        if (INDICES.has(symbol)) {
            updateIndexCard(symbol, marketData);
        } else {
            updateStockRow(symbol, marketData);
        }
    }
    updateLeaderHighlight();
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

    if (INDICES.has(symbol)) {
        updateIndexCard(symbol, data);
    } else {
        updateStockRow(symbol, data);
        updateLeaderHighlight();
        updateMarketStats();

        // Feed live updates to the historical candlestick chart
        if (symbol.toUpperCase() === selectedSymbol.toUpperCase()) {
            updateLiveCandle(data);
        }
    }
}

/* -------------------------------------------------------------
   WEBSOCKET
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

/* -------------------------------------------------------------
   HISTORICAL CHARTING (TRADINGVIEW LIGHTWEIGHT CHARTS)
   ------------------------------------------------------------- */
/** @type {any} */
let chart;
/** @type {any} */
let candleSeries;
let selectedSymbol = "RELIANCE";
let currentCandles = [];
let lastCumulativeVolume = null;

/**
 * Parses an ISO date/time string (e.g. 2026-06-15T11:17:00 or 2026-06-15 11:17:22.541231)
 * as LOCAL time (browser timezone = IST) by always using the local Date constructor.
 *
 * CRITICAL: Do NOT use new Date(isoString) directly.
 * V8/Chrome parses bare ISO strings like "2026-06-15T11:17:00" (no timezone offset)
 * as UTC, which would show 05:47 IST instead of 11:17 IST.
 * We always extract date/time parts and pass them to new Date(y,m,d,h,min,sec)
 * which always interprets values as local time.
 *
 * @param {string} isoString  - e.g. "2026-06-15T11:17:22.541231" or "2026-06-15 11:17:00"
 * @returns {number} Unix epoch seconds relative to local browser timezone (IST)
 */
function parseISOToLocalSeconds(isoString) {
    if (!isoString) return NaN;
    // Normalize space separator to 'T'
    const s = String(isoString).replace(' ', 'T');
    // Split on any non-digit: handles both "T" separator and fractional seconds
    const parts = s.split(/\D/);
    if (parts.length < 5) return NaN;
    const year   = parseInt(parts[0], 10);
    const month  = parseInt(parts[1], 10) - 1; // 0-indexed
    const day    = parseInt(parts[2], 10);
    const hour   = parseInt(parts[3], 10);
    const minute = parseInt(parts[4], 10);
    const second = parseInt(parts[5] || '0', 10);
    
    // Treat parsed numbers as UTC time
    const utcTimeMs = Date.UTC(year, month, day, hour, minute, second);
    // Since the database time is in IST (UTC+5:30), the true UTC timestamp is 5.5 hours earlier
    return (utcTimeMs / 1000) - (5.5 * 3600);
}

function initializeChart() {
    const container = getEl("chart-container");
    if (!container) return;

    const width = container.clientWidth || 800;

    // Create the chart instance.
    // We explicitly format timescale tick marks and crosshair/tooltips in Asia/Kolkata (IST) timezone
    // so that the chart remains correct regardless of client browser locale.
    chart = LightweightCharts.createChart(container, {
        width: width,
        height: 500,
        layout: {
            background: { type: 'solid', color: '#ffffff' },
            backgroundColor: "#ffffff",
            textColor: "#111827",
            fontFamily: "Inter, sans-serif",
        },
        grid: {
            vertLines: { color: "#f3f4f6" },
            horzLines: { color: "#f3f4f6" },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: "#e5e7eb",
        },
        localization: {
            timeFormatter: (timestamp) => {
                const date = new Date(timestamp * 1000);
                return date.toLocaleTimeString('en-US', {
                    timeZone: 'Asia/Kolkata',
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: false
                });
            }
        },
        timeScale: {
            borderColor: "#e5e7eb",
            timeVisible: true,
            secondsVisible: false,
            tickMarkFormatter: (time, tickMarkType, locale) => {
                const date = new Date(time * 1000);
                return date.toLocaleTimeString('en-US', {
                    timeZone: 'Asia/Kolkata',
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: false
                });
            }
        },
    });

    // Add candlestick series configured with the theme green/red colors
    candleSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {
        upColor: "#16a34a",
        downColor: "#dc2626",
        borderDownColor: "#dc2626",
        borderUpColor: "#16a34a",
        wickDownColor: "#dc2626",
        wickUpColor: "#16a34a",
    });

    // Handle container resize automatically
    window.addEventListener("resize", () => {
        chart.resize(container.clientWidth || 800, 500);
    });
}

async function loadCandles(symbol) {
    selectedSymbol = symbol;
    lastCumulativeVolume = null; // Reset volume accumulator for the new symbol
    
    // Update chart title
    const titleEl = getEl("chart-title");
    if (titleEl) {
        titleEl.textContent = `${symbol} - 1 Minute Candles`;
    }

    // Update row highlighting
    document.querySelectorAll(".stock-row").forEach(row => {
        if (row.getAttribute("data-symbol") === symbol) {
            row.classList.add("selected-row");
        } else {
            row.classList.remove("selected-row");
        }
    });

    try {
        const response = await fetch(`http://127.0.0.1:8000/candles/${symbol}?limit=100`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Map, sort, and deduplicate data to prevent Lightweight Charts sorting crashes
        const seenTimes = new Set();
        const mappedData = data.map(candle => ({
            time: parseISOToLocalSeconds(candle.candle_start),
            open: Number(candle.open),
            high: Number(candle.high),
            low: Number(candle.low),
            close: Number(candle.close),
            volume: Number(candle.volume || 0)
        })).filter(c => !isNaN(c.time));

        // Sort ascending chronologically
        mappedData.sort((a, b) => a.time - b.time);

        // Deduplicate matching times
        const cleanData = [];
        for (const item of mappedData) {
            if (!seenTimes.has(item.time)) {
                seenTimes.add(item.time);
                cleanData.push(item);
            }
        }

        if (candleSeries) {
            currentCandles = cleanData;
            candleSeries.setData(currentCandles);
            chart.timeScale().fitContent();
        }
    } catch (err) {
        console.error(`[Dashboard] Failed to load candles for ${symbol}:`, err);
    }
}

function updateLiveCandle(data) {
    // Temporary diagnostic logging
    console.log(
        "LIVE TICK:",
        data.symbol,
        data.timestamp,
        data.ltp
    );
    console.log(
        "SELECTED:",
        selectedSymbol
    );

    if (!candleSeries) return;

    const tickSeconds = parseISOToLocalSeconds(data.timestamp);
    if (isNaN(tickSeconds)) return;

    // Truncate to the start of the current minute (in local seconds)
    const minuteStartSeconds = Math.floor(tickSeconds / 60) * 60;

    const tickVolume = Number(data.volume) || 0;
    let volumeDiff = 0;
    if (lastCumulativeVolume !== null) {
        volumeDiff = Math.max(0, tickVolume - lastCumulativeVolume);
    }
    lastCumulativeVolume = tickVolume;

    if (currentCandles.length === 0) {
        const firstCandle = {
            time: minuteStartSeconds,
            open: Number(data.ltp),
            high: Number(data.ltp),
            low: Number(data.ltp),
            close: Number(data.ltp),
            volume: volumeDiff
        };

        currentCandles.push(firstCandle);
        candleSeries.setData(currentCandles);
        chart.timeScale().scrollToRealTime();
        return;
    }

    const lastCandle = currentCandles[currentCandles.length - 1];

    if (minuteStartSeconds === lastCandle.time) {
        // Update the active 1-minute candle
        lastCandle.close = Number(data.ltp);
        if (Number(data.ltp) > lastCandle.high) lastCandle.high = Number(data.ltp);
        if (Number(data.ltp) < lastCandle.low) lastCandle.low = Number(data.ltp);
        lastCandle.volume = (lastCandle.volume || 0) + volumeDiff;

        candleSeries.update(lastCandle);
        chart.timeScale().scrollToRealTime();
    } else if (minuteStartSeconds > lastCandle.time) {
        // Roll over and create a new active 1-minute candle
        const newCandle = {
            time: minuteStartSeconds,
            open: Number(data.ltp),
            high: Number(data.ltp),
            low: Number(data.ltp),
            close: Number(data.ltp),
            volume: volumeDiff
        };
        currentCandles.push(newCandle);
        candleSeries.update(newCandle);
        chart.timeScale().scrollToRealTime();
    }
}

function setupStockSelection() {
    // Bind click listener to each watchlist stock row
    document.querySelectorAll(".stock-row").forEach(row => {
        row.addEventListener("click", () => {
            const symbol = row.getAttribute("data-symbol");
            if (symbol) {
                loadCandles(symbol);
            }
        });
    });
}

/* -------------------------------------------------------------
   ENTRY POINT
   ------------------------------------------------------------- */
document.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();
    updateHeaderClock();
    setInterval(updateHeaderClock, 1000);
    
    // Initialize chart and load default symbol candles
    initializeChart();
    loadCandles(selectedSymbol);
    setupStockSelection();
});
