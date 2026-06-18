/* =============================================================
   dashboard.js  –  Dashboard UI updates, formats, and event setup
   ============================================================= */

'use strict';

console.info("[Dashboard] Module loaded.");

const TOTAL_STOCKS_COUNT = 8; // Watchlist stock count

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
            if (symbol) {
                loadCandles(symbol);
            }
        });
    });
}

function setupTimeframeSelection() {
    document.querySelectorAll(".timeframe-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const interval = btn.getAttribute("data-interval");
            if (interval) {
                loadCandles(selectedSymbol, interval);
            }
        });
    });
}

/**
 * Dynamically loads and renders stock watchlist rows based on favorite active instruments.
 * Falls back to all active instruments if no favorites are selected.
 */
async function loadWatchlist() {
    const tableBody = document.getElementById("stocks-table-body");
    const indicesContainer = document.getElementById("indices-container");
    const notification = document.getElementById("watchlist-notification");
    if (!tableBody) return;

    // --- Scroll Preservation (Issue 2) ---
    const scrollContainer = tableBody.closest('.table-responsive');
    const savedScrollTop = scrollContainer ? scrollContainer.scrollTop : 0;
    const savedSelectedSymbol = selectedSymbol;

    try {
        const favorites = await getFavoriteInstruments();
        
        // 1. Process INDEX instruments (Show favorite indices, max 3)
        //    Fallback: if no favorites, show NIFTY50, BANKNIFTY, SENSEX from active instruments.
        let indexDisplay = favorites.filter(inst => (inst.instrument_category || '').toUpperCase() === 'INDEX').slice(0, 3);

        if (indexDisplay.length === 0) {
            // Fallback: load known default indices from all active instruments
            const allInstruments = await getInstruments();
            const defaultIndexSymbols = ['NIFTY50', 'BANKNIFTY', 'SENSEX'];
            indexDisplay = allInstruments.filter(inst =>
                inst.active === true &&
                (inst.instrument_category || '').toUpperCase() === 'INDEX' &&
                defaultIndexSymbols.includes(inst.symbol)
            ).slice(0, 3);
        }

        if (indicesContainer) {
            if (indexDisplay.length === 0) {
                indicesContainer.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-secondary); padding: 16px; background: var(--bg-card); border-radius: var(--radius-lg); border: 1px solid var(--border-color); font-size: 13px;">No index instruments found. Add INDEX instruments in Instrument Manager.</div>`;
            } else {
                indicesContainer.innerHTML = "";
                indexDisplay.forEach(ind => {
                    const card = document.createElement("div");
                    card.className = "index-card";
                    card.id = `index-card-${ind.symbol}`;
                    card.setAttribute("data-symbol", ind.symbol);
                    
                    let pathD = "M0,20 Q15,5 30,18 T60,8 T90,14 L100,5"; // Default sparkline path
                    if (ind.symbol === "BANKNIFTY") {
                        pathD = "M0,15 Q15,25 30,10 T60,22 T90,5 L100,12";
                    } else if (ind.symbol === "SENSEX") {
                        pathD = "M0,22 Q15,8 30,20 T60,5 T90,18 L100,10";
                    }

                    card.innerHTML = `
                        <div class="index-header">
                            <span class="index-symbol">${ind.name || ind.symbol}</span>
                            <span class="index-badge">${ind.exchange}</span>
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

        // 2. Process STOCK instruments (Show favorite stocks, fallback to first 10 active stocks)
        let displayStocks = favorites.filter(inst => (inst.instrument_category || '').toUpperCase() === 'STOCK');
        let fallback = false;

        if (displayStocks.length === 0) {
            fallback = true;
            console.warn("[Dashboard] Zero favorite stocks found. Falling back to active stocks.");
            const allInstruments = await getInstruments();
            displayStocks = allInstruments
                .filter(inst => inst.active === true && (inst.instrument_category || '').toUpperCase() === 'STOCK')
                .slice(0, 10);
        }

        if (displayStocks.length === 0) {
            if (notification) {
                notification.textContent = "No active stocks found in database. Please go to Instrument Manager to add stock instruments.";
                notification.style.display = "block";
            }
            tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-secondary); padding: 24px;">No stocks configured.</td></tr>`;
            return;
        }

        if (fallback) {
            if (notification) {
                notification.textContent = "Showing all active stocks (no favorite stocks selected).";
                notification.style.display = "block";
            }
        } else {
            if (notification) {
                notification.style.display = "none";
            }
        }

        tableBody.innerHTML = "";
        
        // Dynamically populate stocks watchlist table
        displayStocks.forEach(inst => {
            const tr = document.createElement("tr");
            tr.className = "stock-row";
            tr.id = `stock-row-${inst.symbol}`;
            tr.setAttribute("data-symbol", inst.symbol);

            const star = inst.is_favorite ? "★" : "☆";
            const starClass = inst.is_favorite ? "star-active" : "";

            tr.innerHTML = `
                <td class="stock-symbol font-medium">
                    <span class="star-icon ${starClass}" onclick="handleDashboardFavoriteToggle(event, '${inst.symbol}', ${inst.is_favorite})">${star}</span>
                    ${inst.symbol}
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

        // Preserve selected symbol; only change if it's no longer in the list
        const symbolStillPresent = displayStocks.some(s => s.symbol === savedSelectedSymbol);
        if (!symbolStillPresent && displayStocks.length > 0) {
            selectedSymbol = displayStocks[0].symbol;
        }

        setupStockSelection();

        // --- Restore Scroll Position (Issue 2) ---
        if (scrollContainer) {
            scrollContainer.scrollTop = savedScrollTop;
        }
        console.log("Render complete.");
        return [...indexDisplay.map(ind => ind.symbol), ...displayStocks.map(s => s.symbol)];
    } catch (err) {
        console.error("Failed to load watchlist:", err);
        tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--color-negative); padding: 24px;">Error loading watchlist: ${err.message}</td></tr>`;
        return [];
    }
}

/**
 * Handles toggling favorite status directly from the Dashboard watchlist.
 * Optimistic UI provides instant star feedback, then loadWatchlist()
 * refreshes both index cards and stock rows with scroll preservation.
 */
async function handleDashboardFavoriteToggle(event, symbol, currentStatus) {
    console.log("FAVORITE CLICK DETECTED", symbol);
    event.stopPropagation(); // Prevent triggering stock selection click

    const starEl = event.target;
    const newStatus = !currentStatus;

    // --- Optimistic UI: flip the star instantly ---
    starEl.textContent = newStatus ? '★' : '☆';
    if (newStatus) {
        starEl.classList.add('star-active');
    } else {
        starEl.classList.remove('star-active');
    }

    try {
        const responseData = await toggleInstrumentFavorite(symbol, newStatus);
        console.log("PATCH SUCCESS", responseData);

        const immediateFavs = await getFavoriteInstruments();
        console.log("Favorites API returned:");
        immediateFavs.forEach(f => console.log(f.symbol));

        // Refresh dashboard: reloads both index cards and watchlist
        // with scroll position and selected row preserved.
        const rendered = await loadWatchlist();
        console.log("Rendered:");
        rendered.forEach(s => console.log(s));
    } catch (err) {
        console.error(`Failed to toggle favorite from dashboard for ${symbol}:`, err);
        // --- Revert on failure ---
        starEl.textContent = currentStatus ? '★' : '☆';
        if (currentStatus) {
            starEl.classList.add('star-active');
        } else {
            starEl.classList.remove('star-active');
        }
    }
}
