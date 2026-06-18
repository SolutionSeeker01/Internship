/* =============================================================
   dashboard.js  –  Dashboard UI updates, formats, and event setup
   ============================================================= */

'use strict';

console.info("[Dashboard] Module loaded.");

const INDICES = new Set(['NIFTY50', 'BANKNIFTY', 'SENSEX']);
const TOTAL_STOCKS_COUNT = 8; // Watchlist stock count

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
   STOCK SELECTION & TIMEFRAME BINDINGS
   ------------------------------------------------------------- */

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

function setupTimeframeSelection() {
    console.log(
        "Timeframe selector:",
        document.querySelector(".timeframe-selector")
    );
    document.querySelectorAll(".timeframe-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const interval = btn.getAttribute("data-interval");
            if (interval) {
                loadCandles(selectedSymbol, interval);
            }
        });
    });
}
