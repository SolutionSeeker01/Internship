/* =============================================================
   instruments.js  –  Instrument Manager view controller and events
   ============================================================= */

'use strict';

console.info("[Instruments] Module loaded.");

/**
 * In-memory cache for the full instruments list.
 * Invalidated on: Add, Delete, Toggle Favorite, Sync, Clear All.
 * Search always bypasses the cache and uses the backend API.
 * @type {Array|null}
 */
let cachedInstruments = null;

/**
 * Invalidates the cached instruments list, forcing a fresh fetch on next load.
 */
function invalidateInstrumentsCache() {
    cachedInstruments = null;
    console.info("[Instruments] Cache invalidated.");
}

/**
 * Switch view between Dashboard and Instrument Manager.
 * @param {'dashboard'|'instruments'} view 
 */
function switchView(view) {
    const dbLayout = document.getElementById("dashboard-layout");
    const instLayout = document.getElementById("instruments-layout");
    const navDashboard = document.getElementById("nav-btn-dashboard");
    const navInstruments = document.getElementById("nav-btn-instruments");

    if (view === "dashboard") {
        dbLayout.style.display = "flex";
        instLayout.style.display = "none";
        navDashboard.classList.add("active");
        navInstruments.classList.remove("active");
        loadWatchlist(); // Dynamic reload
    } else {
        dbLayout.style.display = "none";
        instLayout.style.display = "flex";
        navDashboard.classList.remove("active");
        navInstruments.classList.add("active");
        const searchInput = document.getElementById("search-instruments-input");
        if (searchInput) {
            searchInput.value = "";
        }
        invalidateInstrumentsCache();
        loadInstrumentsManagerTable();
    }
}

/**
 * Loads and renders all existing instruments in the Instrument Manager table.
 * Uses cached data when available (non-search). Search always hits the backend.
 * When using cached data, renders instantly without a "Loading..." flash.
 */
async function loadInstrumentsManagerTable() {
    const tableBody = document.getElementById("instruments-table-body");
    if (!tableBody) return;

    try {
        if (cachedInstruments !== null) {
            renderInstrumentsTable(tableBody, cachedInstruments);
            console.info("[Instruments] Using cached favorites.");
        } else {
            tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-secondary); padding: 24px;">Loading watchlist...</td></tr>`;
            const instruments = (await getFavoriteInstruments()).filter(inst => inst.is_favorite);
            cachedInstruments = instruments;
            console.info("[Instruments] Fetched and cached favorites.");
            renderInstrumentsTable(tableBody, instruments);
        }
    } catch (err) {
        console.error("Failed to load instruments table:", err);
        tableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--color-negative); padding: 24px;">Error loading instruments: ${err.message}</td></tr>`;
    }
}

/**
 * Renders instrument rows into the given table body element.
 * Extracted to avoid duplication between cached and fetched paths.
 * @param {HTMLElement} tableBody
 * @param {Array} instruments
 */
function renderInstrumentsTable(tableBody, instruments) {
    if (instruments.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-secondary); padding: 24px;">No instruments in watchlist. Search above to add.</td></tr>`;
        return;
    }

    tableBody.innerHTML = "";
    instruments.forEach(inst => {
        const tr = document.createElement("tr");
        tr.className = "instrument-row";
        tr.setAttribute("data-symbol", inst.symbol);
        tr.setAttribute("data-exchange", inst.exchange);

        tr.innerHTML = `
            <td class="font-medium">${inst.symbol}</td>
            <td>${inst.token}</td>
            <td>${inst.exchange}</td>
            <td>${inst.name}</td>
            <td>${inst.segment}</td>
            <td>${inst.broker}</td>
            <td>${inst.instrument_category || 'STOCK'}</td>
            <td class="text-right" style="padding-right: 24px;">
                <div class="action-btn-group">
                    <button class="btn-action btn-fav ${inst.is_favorite ? 'active' : ''}" onclick="handleToggleFavorite('${inst.symbol}', '${inst.exchange}', ${inst.is_favorite})">
                        ${inst.is_favorite ? '★ Favorite' : '☆ Favorite'}
                    </button>
                    <button class="btn-action btn-delete" onclick="handleDeleteInstrument('${inst.symbol}', '${inst.exchange}')">
                        Delete
                    </button>
                </div>
            </td>
        `;
        tableBody.appendChild(tr);
    });
}

/**
 * Renders search results in the dropdown container.
 * @param {Array} results 
 */
function renderSearchDropdown(results) {
    const dropdown = document.getElementById("search-results-dropdown");
    if (!dropdown) return;

    dropdown.innerHTML = "";
    if (results.length === 0) {
        dropdown.innerHTML = `<div style="padding: 12px; text-align: center; color: var(--text-secondary); font-size: 13px;">No results found</div>`;
    } else {
        results.forEach(inst => {
            const item = document.createElement("div");
            item.style.padding = "10px 12px";
            item.style.borderBottom = "1px solid var(--border-color)";
            item.style.cursor = "pointer";
            item.style.display = "flex";
            item.style.justifyContent = "space-between";
            item.style.alignItems = "center";
            item.style.background = "#ffffff";
            item.style.transition = "background 0.2s";

            item.addEventListener("mouseenter", () => {
                item.style.background = "var(--bg-body)";
            });
            item.addEventListener("mouseleave", () => {
                item.style.background = "#ffffff";
            });
            
            // Check if this is already in the watchlist/favorites
            const isFav = cachedInstruments ? cachedInstruments.some(c => c.symbol === inst.symbol && c.exchange === inst.exchange && c.is_favorite) : inst.is_favorite;
            
            item.innerHTML = `
                <div style="display: flex; flex-direction: column; min-width: 0;">
                    <span style="font-weight: 600; font-size: 13px; color: var(--text-primary);">${inst.symbol} <span style="font-size: 10px; color: var(--text-secondary); background: var(--bg-card); padding: 2px 4px; border-radius: 4px; margin-left: 4px;">${inst.exchange}</span></span>
                    <span style="font-size: 11px; color: var(--text-secondary); text-overflow: ellipsis; white-space: nowrap; overflow: hidden; max-width: 250px;">${inst.name}</span>
                </div>
                <button class="btn-action btn-fav ${isFav ? 'active' : ''}" style="margin-left: auto; padding: 4px 8px; font-size: 11px; margin-top: 0; min-height: 28px;" onclick="event.stopPropagation(); handleSearchToggleFavorite('${inst.symbol}', '${inst.exchange}', ${isFav})">
                    ${isFav ? '★ Favorite' : '☆ Add'}
                </button>
            `;
            dropdown.appendChild(item);
        });
    }
    dropdown.style.display = "block";
}

/**
 * Handles toggling favorite state from the search results dropdown.
 */
async function handleSearchToggleFavorite(symbol, exchange, currentStatus) {
    const newStatus = !currentStatus;
    try {
        await toggleInstrumentFavorite(symbol, exchange, newStatus);
        invalidateInstrumentsCache();
        
        // Reload the watchlist table (extremely fast since watchlist is small)
        await loadInstrumentsManagerTable();
        
        // Re-render search dropdown to show updated favorite status
        const searchInput = document.getElementById("search-instruments-input");
        if (searchInput) {
            const results = await searchInstruments(searchInput.value.trim());
            renderSearchDropdown(results);
        }
    } catch (err) {
        console.error(`Failed to toggle favorite from search for ${symbol} (${exchange}):`, err);
        alert(`Error: ${err.message}`);
    }
}

/**
 * Handles "Add Instrument" form submission.
 */
async function handleAddInstrumentSubmit() {
    const symbolInput = document.getElementById("form-symbol");
    const tokenInput = document.getElementById("form-token");
    const exchangeInput = document.getElementById("form-exchange");
    const nameInput = document.getElementById("form-name");
    const segmentInput = document.getElementById("form-segment");
    const categoryInput = document.getElementById("form-category");
    const brokerInput = document.getElementById("form-broker");

    const payload = {
        symbol: symbolInput.value.toUpperCase().trim(),
        token: parseInt(tokenInput.value),
        exchange: exchangeInput.value,
        name: nameInput.value.trim(),
        segment: segmentInput.value,
        instrument_category: categoryInput.value,
        broker: brokerInput.value.trim()
    };

    try {
        const result = await createInstrument(payload);
        alert(result.message || "Instrument added successfully. Use search to find and add it to your watchlist.");
        
        // Reset form inputs (except broker default)
        symbolInput.value = "";
        tokenInput.value = "";
        nameInput.value = "";
        exchangeInput.selectedIndex = 0;
        segmentInput.selectedIndex = 0;
        categoryInput.selectedIndex = 0;
        
        // Invalidate cache
        invalidateInstrumentsCache();
    } catch (err) {
        console.error("Failed to add instrument:", err);
        alert(`Failed to add instrument: ${err.message}`);
    }
}

/**
 * Handles toggling favorite state of an instrument in the watchlist table.
 * Row-level update: only the affected button is modified in-place.
 */
async function handleToggleFavorite(symbol, exchange, currentStatus) {
    const newStatus = !currentStatus;

    try {
        await toggleInstrumentFavorite(symbol, exchange, newStatus);
        invalidateInstrumentsCache();

        // --- Row-level DOM update (no table rebuild) ---
        const row = document.querySelector(`.instrument-row[data-symbol="${symbol}"][data-exchange="${exchange}"]`);
        if (row) {
            if (!newStatus) {
                // Removing from watchlist: remove row immediately
                row.remove();
                const tableBody = document.getElementById("instruments-table-body");
                if (tableBody && tableBody.children.length === 0) {
                    tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-secondary); padding: 24px;">No instruments in watchlist. Search above to add.</td></tr>`;
                }
            } else {
                const favBtn = row.querySelector('.btn-fav');
                if (favBtn) {
                    favBtn.textContent = '★ Favorite';
                    favBtn.classList.add('active');
                    favBtn.setAttribute('onclick', `handleToggleFavorite('${symbol}', '${exchange}', ${newStatus})`);
                }
            }
        }
    } catch (err) {
        console.error(`Failed to toggle favorite for ${symbol} (${exchange}):`, err);
        alert(`Error: ${err.message}`);
    }
}

/**
 * Handles deletion of an instrument.
 */
async function handleDeleteInstrument(symbol, exchange) {
    if (!confirm(`Are you sure you want to delete the instrument: ${symbol} (${exchange})?`)) {
        return;
    }

    try {
        const result = await deleteInstrument(symbol, exchange);
        alert(result.message || `${symbol} deleted successfully.`);
        invalidateInstrumentsCache();
        
        // Row-level DOM update
        const row = document.querySelector(`.instrument-row[data-symbol="${symbol}"][data-exchange="${exchange}"]`);
        if (row) {
            row.remove();
            const tableBody = document.getElementById("instruments-table-body");
            if (tableBody && tableBody.children.length === 0) {
                tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-secondary); padding: 24px;">No instruments in watchlist. Search above to add.</td></tr>`;
            }
        }
    } catch (err) {
        console.error(`Failed to delete ${symbol} (${exchange}):`, err);
        alert(`Error: ${err.message}`);
    }
}

/**
 * Reads checked filters, submits post request to sync endpoint, and renders metrics.
 */
async function handleSyncInstruments() {
    const btn = document.getElementById("btn-sync-instruments");
    const statusMsg = document.getElementById("sync-status-msg");
    if (!btn || !statusMsg) return;

    // Collect Exchanges - NSE-only branch requirement
    const exchanges = ["NSE"];

    // Collect Segments
    const segments = [];
    if (document.getElementById("sync-seg-eq")?.checked) segments.push("EQ");
    if (document.getElementById("sync-seg-ind")?.checked) segments.push("IND");
    if (document.getElementById("sync-seg-etf")?.checked) segments.push("ETF");
    if (document.getElementById("sync-seg-fut")?.checked) segments.push("FUT");
    if (document.getElementById("sync-seg-opt")?.checked) segments.push("OPT");

    if (exchanges.length === 0 || segments.length === 0) {
        alert("Please select at least one exchange and one segment to sync.");
        return;
    }

    try {
        btn.disabled = true;
        btn.textContent = "Syncing...";
        statusMsg.style.display = "block";
        statusMsg.style.color = "var(--text-secondary)";
        statusMsg.textContent = "Connecting to Zerodha and importing data...";

        const result = await syncInstruments(exchanges, segments);

        statusMsg.style.color = "var(--accent-blue)";
        statusMsg.textContent = `Sync Complete!\nImported: ${result.imported}\nUpdated: ${result.updated}\nSkipped: ${result.skipped}`;
        
        // Full refresh on sync complete
        invalidateInstrumentsCache();
        loadInstrumentsManagerTable();
    } catch (err) {
        console.error("Instrument sync failed:", err);
        statusMsg.style.color = "var(--color-negative)";
        statusMsg.textContent = `Sync Failed: ${err.message}`;
    } finally {
        btn.disabled = false;
        btn.textContent = "Sync Instruments";
    }
}

/**
 * Handles clearing ALL instruments with a confirmation dialog.
 */
async function handleClearAllInstruments() {
    if (!confirm("⚠️ Are you sure you want to delete ALL instruments?\n\nThis action cannot be undone. All instruments, favorites, and synced data will be removed.")) {
        return;
    }

    const btn = document.getElementById("btn-clear-all-instruments");
    try {
        if (btn) {
            btn.disabled = true;
            btn.textContent = "Clearing...";
        }
        const result = await clearAllInstruments();
        alert(result.message || "All instruments cleared.");
        invalidateInstrumentsCache();
        
        const tableBody = document.getElementById("instruments-table-body");
        if (tableBody) {
            tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-secondary); padding: 24px;">No instruments in watchlist. Search above to add.</td></tr>`;
        }
    } catch (err) {
        console.error("Failed to clear all instruments:", err);
        alert(`Error: ${err.message}`);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = "Clear All Instruments";
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById("search-instruments-input");
    const dropdown = document.getElementById("search-results-dropdown");

    if (searchInput && dropdown) {
        let searchDebounceTimer = null;
        searchInput.addEventListener("input", (e) => {
            clearTimeout(searchDebounceTimer);
            const query = e.target.value.trim();
            if (!query) {
                dropdown.innerHTML = "";
                dropdown.style.display = "none";
                return;
            }
            searchDebounceTimer = setTimeout(async () => {
                try {
                    const results = await searchInstruments(query);
                    renderSearchDropdown(results);
                } catch (err) {
                    console.error("Search failed:", err);
                }
            }, 300);
        });

        // Hide dropdown when clicking outside
        document.addEventListener("click", (e) => {
            if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
                dropdown.style.display = "none";
            }
        });

        // Show dropdown on focus if it has content
        searchInput.addEventListener("focus", () => {
            if (dropdown.children.length > 0) {
                dropdown.style.display = "block";
            }
        });
    }
});
