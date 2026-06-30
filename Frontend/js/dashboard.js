/* =============================================================
   dashboard.js  –  Dashboard UI updates, formats, and event setup
   ============================================================= */

'use strict';

console.info("[Dashboard] Module loaded.");

let TOTAL_STOCKS_COUNT = 8; // Dynamically updated based on active selection count

/**
 * Tracks the last known LTP for every symbol so we can determine
 * whether a new tick is higher or lower (for flash animations).
 * @type {Map<string, number>}
 */
const previousLtp = new Map();

/**
 * Tracks the current change % for all active stocks to compute breadth.
 * @type {Map<string, number>}
 */
const currentChanges = new Map();

/**
 * Tracks the latest market data tick for every symbol.
 * @type {Map<string, object>}
 */
const latestMarketData = new Map();

// Local state for dashboard watchlist selection
// Synchronously restore selectedWatchlistId from localStorage at script load time
// to guarantee it is available before any async DOMContentLoaded handlers execute.
const _savedWatchlistId = localStorage.getItem("dashboard_selected_watchlist_id");
const state = {
    watchlists: [],
    selectedWatchlistId: _savedWatchlistId ? parseInt(_savedWatchlistId, 10) : null
};

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
   MARKET STATISTICS / BREADTH
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
        if (document.getElementById(`index-card-${symbol}`)) continue;
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
            const exchange = row.getAttribute("data-exchange");
            if (symbol) {
                loadCandles(symbol, exchange);
            }
        });
    });
}

function setupIndexSelection() {
    // Bind click listener to each indices card
    document.querySelectorAll(".index-card").forEach(card => {
        card.addEventListener("click", () => {
            const symbol = card.getAttribute("data-symbol");
            const exchange = card.getAttribute("data-exchange");
            if (symbol) {
                loadCandles(symbol, exchange);
            }
        });
    });
}

function setupTimeframeSelection() {
    document.querySelectorAll(".timeframe-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const interval = btn.getAttribute("data-interval");
            if (interval) {
                loadCandles(selectedSymbol, null, interval);
            }
        });
    });
}

/**
 * Dynamically loads and renders the dashboard watchlist using the dedicated
 * GET /dashboard/watchlist endpoint. The backend owns all business logic.
 */
async function loadWatchlist() {
    const tableBody = document.getElementById("stocks-table-body");
    const indicesContainer = document.getElementById("indices-container");
    const notification = document.getElementById("watchlist-notification");
    if (!tableBody) return;

    // --- Scroll Preservation ---
    const scrollContainer = tableBody.closest('.table-responsive');
    const savedScrollTop = scrollContainer ? scrollContainer.scrollTop : 0;
    const savedSelectedSymbol = selectedSymbol;

    try {
        const watchlist = await getDashboardWatchlist(state.selectedWatchlistId);
        const { indices, stocks, view_mode } = watchlist;

        TOTAL_STOCKS_COUNT = stocks.length;

        // ── Banners ────────────────────────────────
        if (notification) {
            if (view_mode === "empty") {
                notification.textContent = "This watchlist does not contain any instruments.";
                notification.style.display = "block";
            } else if (view_mode === "fallback") {
                notification.textContent = "Showing Default Market View";
                notification.style.display = "block";
            } else {
                notification.style.display = "none";
            }
        }

        // ── Render Indices ──────────────────────────────────────
        if (indicesContainer) {
            if (indices.length === 0) {
                indicesContainer.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-secondary); padding: 16px; background: var(--bg-card); border-radius: var(--radius-lg); border: 1px solid var(--border-color); font-size: 13px;">No index instruments found.</div>`;
            } else {
                indicesContainer.innerHTML = "";
                indices.forEach(ind => {
                    const card = document.createElement("div");
                    card.className = "index-card";
                    card.id = `index-card-${ind.symbol}`;
                    card.setAttribute("data-symbol", ind.symbol);
                    card.setAttribute("data-exchange", ind.exchange);

                    let pathD = "M0,20 Q15,5 30,18 T60,8 T90,14 L100,5"; // Default sparkline path
                    if (ind.symbol === "BANKNIFTY") {
                        pathD = "M0,15 Q15,25 30,10 T60,22 T90,5 L100,12";
                    } else if (ind.symbol === "SENSEX") {
                        pathD = "M0,22 Q15,8 30,20 T60,5 T90,18 L100,10";
                    }

                    card.innerHTML = `
                        <div class="index-header">
                            <span class="index-symbol">${ind.symbol} | ${ind.exchange}</span>
                        </div>
                        <div class="index-body-wrapper">
                            <div class="index-values">
                                <div class="index-ltp" id="index-ltp-${ind.symbol}">--</div>
                                <div class="index-change" id="index-change-${ind.symbol}">--</div>
                            </div>
                            <div class="index-sparkline">
                                <svg viewBox="0 0 100 30" class="sparkline-svg">
                                    <path d="${pathD}" fill="none" stroke="#6b7280" stroke-width="1.5" stroke-linecap="round"></path>
                                </svg>
                            </div>
                        </div>
                    `;
                    indicesContainer.appendChild(card);
                    if (latestMarketData.has(ind.symbol)) {
                        updateIndexCard(ind.symbol, latestMarketData.get(ind.symbol));
                    }
                });
            }
        }

        // ── Render Stocks ───────────────────────────────────────
        tableBody.innerHTML = "";
        if (view_mode === "empty" || stocks.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-secondary); padding: 24px;">This watchlist does not contain any instruments.</td></tr>`;
            
            // Clear chart gracefully
            selectedSymbol = "";
            if (typeof clearChart === "function") {
                clearChart();
            }
        } else {
            stocks.forEach(inst => {
                const tr = document.createElement("tr");
                tr.className = "stock-row";
                tr.id = `stock-row-${inst.symbol}`;
                tr.setAttribute("data-symbol", inst.symbol);
                tr.setAttribute("data-exchange", inst.exchange);

                tr.innerHTML = `
                    <td class="stock-symbol font-medium">
                        ${inst.symbol} | ${inst.exchange}
                    </td>
                    <td class="stock-ltp text-right" id="stock-ltp-${inst.symbol}">--</td>
                    <td class="stock-change text-right" id="stock-change-${inst.symbol}">--</td>
                    <td class="stock-bid text-right" id="stock-bid-${inst.symbol}">--</td>
                    <td class="stock-ask text-right" id="stock-ask-${inst.symbol}">--</td>
                    <td class="stock-volume text-right" id="stock-volume-${inst.symbol}">--</td>
                    <td class="stock-open text-right" id="stock-open-${inst.symbol}">--</td>
                    <td class="stock-close text-right" id="stock-close-${inst.symbol}">--</td>
                `;

                // Restore selected row highlight
                if (inst.symbol === savedSelectedSymbol) {
                    tr.classList.add('selected-row');
                }

                tableBody.appendChild(tr);
                if (latestMarketData.has(inst.symbol)) {
                    updateStockRow(inst.symbol, latestMarketData.get(inst.symbol));
                }
            });
            setupStockSelection();
        }

        // Preserve selected symbol; clear chart if it's no longer in either list (stocks or indices)
        const symbolStillPresent = stocks.some(s => s.symbol === savedSelectedSymbol && s.exchange === selectedExchange) || 
                                   indices.some(i => i.symbol === savedSelectedSymbol && i.exchange === selectedExchange);
        if (savedSelectedSymbol && !symbolStillPresent) {
            selectedSymbol = "";
            selectedExchange = "";
            if (typeof clearChart === "function") {
                clearChart();
            }
        }

        setupIndexSelection();

        // --- Restore Scroll Position ---
        if (scrollContainer) {
            scrollContainer.scrollTop = savedScrollTop;
        }
    } catch (err) {
        console.error("Failed to load watchlist:", err);
        tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--color-negative); padding: 24px;">Error loading watchlist: ${err.message}</td></tr>`;
    }
}

/**
 * Initializes and populates the watchlist selector dropdown
 */
/**
 * Restores the selected watchlist state from localStorage and updates the dropdown selector.
 */
function restoreSelectedWatchlistState() {
    const savedId = localStorage.getItem("dashboard_selected_watchlist_id");
    const dropdown = document.getElementById("dashboard-watchlist-select");
    
    if (!savedId) {
        state.selectedWatchlistId = null;
        if (dropdown) {
            dropdown.value = "";
        }
        return;
    }

    const parsedId = parseInt(savedId, 10);
    if (state.watchlists && state.watchlists.length > 0) {
        const exists = state.watchlists.some(w => w.id === parsedId);
        if (exists) {
            state.selectedWatchlistId = parsedId;
            if (dropdown) {
                dropdown.value = savedId;
            }
        } else {
            localStorage.removeItem("dashboard_selected_watchlist_id");
            state.selectedWatchlistId = null;
            if (dropdown) {
                dropdown.value = "";
            }
        }
    } else {
        state.selectedWatchlistId = parsedId;
        if (dropdown) {
            dropdown.value = savedId;
        }
    }
}

/**
 * Initializes and populates the watchlist selector dropdown
 */
async function initializeWatchlistDropdown() {
    const dropdown = document.getElementById("dashboard-watchlist-select");
    if (!dropdown) return;

    try {
        state.watchlists = await getWatchlists();

        // Clear dynamic options first (keep default market view option)
        dropdown.innerHTML = '<option value="">Default Market View</option>';

        // Add options for each watchlist
        state.watchlists.forEach(w => {
            const opt = document.createElement("option");
            opt.value = w.id;
            opt.textContent = w.name;
            dropdown.appendChild(opt);
        });

        // Restore state after watchlists options populate
        restoreSelectedWatchlistState();

        // Dropdown switch event listener (bind once)
        dropdown.removeEventListener("change", handleDropdownChange);
        dropdown.addEventListener("change", handleDropdownChange);

    } catch (err) {
        console.error("Failed to load watchlists for dropdown:", err);
    }
}

async function handleDropdownChange(e) {
    const val = e.target.value;
    if (val) {
        state.selectedWatchlistId = parseInt(val, 10);
        localStorage.setItem("dashboard_selected_watchlist_id", val);
    } else {
        state.selectedWatchlistId = null;
        localStorage.removeItem("dashboard_selected_watchlist_id");
    }
    await loadWatchlist();
}

/* -------------------------------------------------------------
   INITIALIZATION CODE
   ------------------------------------------------------------- */

document.addEventListener('DOMContentLoaded', async () => {
    // 1. Initial watchlist dropdown load (fully populated and restored)
    await initializeWatchlistDropdown();

    // 2. Load market instruments lists (guaranteed to run with correct selectedWatchlistId)
    await loadWatchlist();

    // 3. Setup clock timer
    updateHeaderClock();
    setInterval(updateHeaderClock, 1000);

    // 4. Setup sparklines selectors
    setupTimeframeSelection();

    // 5. Connect Socket streams
    connectMarketSocket({
        onOpen: () => updateConnectionStatus('connected'),
        onClose: () => updateConnectionStatus('disconnected'),
        onTick: (symbol, tick) => {
            latestMarketData.set(symbol, tick);
            if (document.getElementById(`index-card-${symbol}`)) {
                updateIndexCard(symbol, tick);
            }
            if (document.getElementById(`stock-row-${symbol}`)) {
                updateStockRow(symbol, tick);
            }
            updateMarketStats();
        }
    });
});
