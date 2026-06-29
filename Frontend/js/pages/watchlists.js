/* =============================================================
   watchlists.js  –  Watchlists view controller
   ============================================================= */

'use strict';

console.info("[Watchlist Manager] Module loaded.");

// State variables managed locally
const state = {
    watchlists: [],
    selectedWatchlistId: null,
    selectedWatchlistItems: []
};

/**
 * Loads all watchlists from backend database and updates view.
 */
async function loadWatchlists() {
    try {
        state.watchlists = await getWatchlists();
        renderWatchlistsList();
        await refreshSelectedWatchlistItems();
        renderWatchlistDetails();
    } catch (err) {
        console.error("Failed to load watchlists list:", err);
        alert(`Failed to load watchlists: ${err.message}`);
    }
}

/**
 * Loads the active watchlist instruments list from backend.
 */
async function refreshSelectedWatchlistItems() {
    if (!state.selectedWatchlistId) {
        state.selectedWatchlistItems = [];
        return;
    }
    try {
        state.selectedWatchlistItems = await getWatchlistItems(state.selectedWatchlistId);
    } catch (err) {
        console.error(`Failed to load items for watchlist ${state.selectedWatchlistId}:`, err);
        state.selectedWatchlistItems = [];
    }
}

/**
 * Renders the watchlists sidebar list on left panel.
 */
function renderWatchlistsList() {
    const listContainer = document.getElementById("watchlists-list");
    if (!listContainer) return;

    if (state.watchlists.length === 0) {
        listContainer.innerHTML = `<div style="padding: 12px; text-align: center; color: var(--text-secondary); font-size: 13px;">No watchlists. Create one below.</div>`;
        return;
    }

    listContainer.innerHTML = "";
    state.watchlists.forEach(watchlist => {
        const item = document.createElement("div");
        item.className = `watchlist-item-row ${watchlist.id === state.selectedWatchlistId ? 'active' : ''}`;
        item.innerHTML = `
            <span>${watchlist.name}</span>
            <span style="font-size: 11px; color: var(--text-secondary);">ID: ${watchlist.id}</span>
        `;
        item.addEventListener("click", async () => {
            state.selectedWatchlistId = watchlist.id;
            renderWatchlistsList();
            await refreshSelectedWatchlistItems();
            renderWatchlistDetails();
        });
        listContainer.appendChild(item);
    });
}

/**
 * Renders detail values and items table on right panel.
 */
function renderWatchlistDetails() {
    const detailsView = document.getElementById("details-view");
    const emptyState = document.getElementById("details-empty-state");
    if (!detailsView || !emptyState) return;

    const current = state.watchlists.find(w => w.id === state.selectedWatchlistId);
    if (!current) {
        detailsView.style.display = "none";
        emptyState.style.display = "flex";
        state.selectedWatchlistId = null;
        return;
    }

    emptyState.style.display = "none";
    detailsView.style.display = "flex";

    document.getElementById("watchlist-detail-name").textContent = current.name;
    document.getElementById("watchlist-detail-id").textContent = current.id;
    
    // Parse created_at format nicely
    let dateStr = "---";
    if (current.created_at) {
        try {
            const dt = new Date(current.created_at);
            dateStr = dt.toLocaleString();
        } catch (e) {
            dateStr = current.created_at;
        }
    }
    document.getElementById("watchlist-detail-created").textContent = dateStr;

    // Reset forms inputs values
    const renameInput = document.getElementById("rename-watchlist-name");
    if (renameInput) renameInput.value = current.name;

    // Render Watchlist Instruments
    renderWatchlistItemsTable();
}

/**
 * Populates table body for watchlist items
 */
function renderWatchlistItemsTable() {
    const tableBody = document.getElementById("watchlist-items-table-body");
    if (!tableBody) return;

    if (state.selectedWatchlistItems.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-secondary); padding: 24px;">This watchlist does not contain any instruments.</td></tr>`;
        return;
    }

    tableBody.innerHTML = "";
    state.selectedWatchlistItems.forEach(item => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td class="font-medium">${item.symbol}</td>
            <td>${item.exchange}</td>
            <td>${item.name}</td>
            <td class="text-right">
                <div class="action-btn-group">
                    <button class="btn-action btn-delete" onclick="handleRemoveItemClick(${item.id})">Remove</button>
                </div>
            </td>
        `;
        tableBody.appendChild(tr);
    });
}

/**
 * Triggered on create form submission.
 */
async function handleCreateWatchlistSubmit() {
    const input = document.getElementById("create-watchlist-name");
    if (!input) return;
    const name = input.value.trim();
    if (!name) return;

    try {
        const newWatchlist = await createWatchlist(name);
        input.value = "";
        state.selectedWatchlistId = newWatchlist.id; // Auto select newly created list
        await loadWatchlists();
    } catch (err) {
        console.error("Failed to create watchlist:", err);
        alert(`Failed to create watchlist: ${err.message}`);
    }
}

/**
 * Triggered on rename form submission.
 */
async function handleRenameWatchlistSubmit() {
    if (!state.selectedWatchlistId) return;
    const input = document.getElementById("rename-watchlist-name");
    if (!input) return;
    const name = input.value.trim();
    if (!name) return;

    try {
        await renameWatchlist(state.selectedWatchlistId, name);
        await loadWatchlists();
    } catch (err) {
        console.error("Failed to rename watchlist:", err);
        alert(`Failed to rename watchlist: ${err.message}`);
    }
}

/**
 * Triggered on delete click.
 */
async function handleDeleteWatchlistClick() {
    if (!state.selectedWatchlistId) return;
    const current = state.watchlists.find(w => w.id === state.selectedWatchlistId);
    if (!current) return;

    if (!confirm(`Are you sure you want to delete the watchlist: "${current.name}"?\nThis action cannot be undone.`)) {
        return;
    }

    try {
        await deleteWatchlist(state.selectedWatchlistId);
        state.selectedWatchlistId = null;
        await loadWatchlists();
    } catch (err) {
        console.error("Failed to delete watchlist:", err);
        alert(`Failed to delete watchlist: ${err.message}`);
    }
}

/**
 * Triggered when user selects a search suggestion to add to watchlist.
 */
async function handleAddInstrumentToWatchlist(instrumentId, symbol) {
    if (!state.selectedWatchlistId) return;
    try {
        await addInstrumentToWatchlist(state.selectedWatchlistId, instrumentId);
        
        // UX: clear the search input and hide suggestions dropdown
        const searchInput = document.getElementById("search-catalog-input");
        if (searchInput) searchInput.value = "";
        const dropdown = document.getElementById("search-catalog-dropdown");
        if (dropdown) {
            dropdown.innerHTML = "";
            dropdown.style.display = "none";
        }

        await refreshSelectedWatchlistItems();
        renderWatchlistDetails();
    } catch (err) {
        console.error("Failed to add instrument to watchlist:", err);
        alert(`Error: ${err.message}`);
    }
}

/**
 * Triggered on removing an instrument from watchlist.
 */
async function handleRemoveItemClick(instrumentId) {
    if (!state.selectedWatchlistId) return;
    if (!confirm("Are you sure you want to remove this instrument from the watchlist?")) return;

    try {
        await removeInstrumentFromWatchlist(state.selectedWatchlistId, instrumentId);
        await refreshSelectedWatchlistItems();
        renderWatchlistDetails();
    } catch (err) {
        console.error("Failed to remove item:", err);
        alert(`Error: ${err.message}`);
    }
}

/**
 * Renders autocomplete suggestions dropdown.
 */
function renderCatalogSearchDropdown(results) {
    const dropdown = document.getElementById("search-catalog-dropdown");
    if (!dropdown) return;

    dropdown.innerHTML = "";
    if (results.length === 0) {
        dropdown.innerHTML = `<div style="padding: 12px; text-align: center; color: var(--text-secondary); font-size: 13px;">No instruments found in catalog.</div>`;
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
            
            const isAlreadyAdded = state.selectedWatchlistItems.some(i => i.id === inst.id);
            
            item.innerHTML = `
                <div style="display: flex; flex-direction: column; min-width: 0;">
                    <span style="font-weight: 600; font-size: 13px; color: var(--text-primary);">${inst.symbol} <span style="font-size: 10px; color: var(--text-secondary); background: var(--bg-card); padding: 2px 4px; border-radius: 4px; margin-left: 4px;">${inst.exchange}</span></span>
                    <span style="font-size: 11px; color: var(--text-secondary); text-overflow: ellipsis; white-space: nowrap; overflow: hidden; max-width: 250px;">${inst.name}</span>
                </div>
                <button class="btn-action btn-fav ${isAlreadyAdded ? 'active' : ''}" style="margin-left: auto; padding: 4px 8px; font-size: 11px; margin-top: 0; min-height: 28px;" onclick="event.stopPropagation(); handleAddInstrumentToWatchlist(${inst.id}, '${inst.symbol}')" ${isAlreadyAdded ? 'disabled' : ''}>
                    ${isAlreadyAdded ? 'Added' : 'Add to Watchlist'}
                </button>
            `;
            dropdown.appendChild(item);
        });
    }
    dropdown.style.display = "block";
}

document.addEventListener('DOMContentLoaded', () => {
    loadWatchlists();

    // Setup autocomplete listeners
    const searchInput = document.getElementById("search-catalog-input");
    const dropdown = document.getElementById("search-catalog-dropdown");

    if (searchInput && dropdown) {
        let debounceTimer = null;
        searchInput.addEventListener("input", (e) => {
            clearTimeout(debounceTimer);
            const query = e.target.value.trim();
            if (!query) {
                dropdown.innerHTML = "";
                dropdown.style.display = "none";
                return;
            }
            debounceTimer = setTimeout(async () => {
                try {
                    const results = await searchInstruments(query);
                    renderCatalogSearchDropdown(results);
                } catch (err) {
                    console.error("Catalog search failed:", err);
                }
            }, 300);
        });

        document.addEventListener("click", (e) => {
            if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
                dropdown.style.display = "none";
            }
        });

        searchInput.addEventListener("focus", () => {
            if (dropdown.children.length > 0) {
                dropdown.style.display = "block";
            }
        });
    }
});
