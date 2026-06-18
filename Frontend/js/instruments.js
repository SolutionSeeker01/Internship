/* =============================================================
   instruments.js  –  Instrument Manager view controller and events
   ============================================================= */

'use strict';

console.info("[Instruments] Module loaded.");

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
        loadInstrumentsManagerTable();
    }
}

/**
 * Loads and renders all existing instruments in the Instrument Manager table.
 */
async function loadInstrumentsManagerTable() {
    const tableBody = document.getElementById("instruments-table-body");
    if (!tableBody) return;

    try {
        tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-secondary); padding: 24px;">Loading instruments...</td></tr>`;
        const instruments = await getInstruments();

        if (instruments.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-secondary); padding: 24px;">No instruments found in database.</td></tr>`;
            return;
        }

        tableBody.innerHTML = "";
        instruments.forEach(inst => {
            const tr = document.createElement("tr");
            tr.className = "instrument-row";
            tr.setAttribute("data-symbol", inst.symbol);

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
                        <button class="btn-action btn-fav ${inst.is_favorite ? 'active' : ''}" onclick="handleToggleFavorite('${inst.symbol}', ${inst.is_favorite})">
                            ${inst.is_favorite ? '★ Favorite' : '☆ Favorite'}
                        </button>
                        <button class="btn-action btn-delete" onclick="handleDeleteInstrument('${inst.symbol}')">
                            Delete
                        </button>
                    </div>
                </td>
            `;
            tableBody.appendChild(tr);
        });
    } catch (err) {
        console.error("Failed to load instruments table:", err);
        tableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--color-negative); padding: 24px;">Error loading instruments: ${err.message}</td></tr>`;
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
        alert(result.message || "Instrument added successfully.");
        
        // Reset form inputs (except broker default)
        symbolInput.value = "";
        tokenInput.value = "";
        nameInput.value = "";
        exchangeInput.selectedIndex = 0;
        segmentInput.selectedIndex = 0;
        categoryInput.selectedIndex = 0;
        
        // Refresh Table
        loadInstrumentsManagerTable();
    } catch (err) {
        console.error("Failed to add instrument:", err);
        alert(`Failed to add instrument: ${err.message}`);
    }
}

/**
 * Handles toggling favorite state of an instrument.
 * Row-level update: only the affected button is modified in-place.
 * No table rebuild, no reorder, no scroll jump.
 */
async function handleToggleFavorite(symbol, currentStatus) {
    console.log("FAVORITE CLICK DETECTED", symbol);
    const newStatus = !currentStatus;

    try {
        await toggleInstrumentFavorite(symbol, newStatus);

        // --- Row-level DOM update (no table rebuild) ---
        const row = document.querySelector(`.instrument-row[data-symbol="${symbol}"]`);
        if (row) {
            const favBtn = row.querySelector('.btn-fav');
            if (favBtn) {
                favBtn.textContent = newStatus ? '★ Favorite' : '☆ Favorite';
                if (newStatus) {
                    favBtn.classList.add('active');
                } else {
                    favBtn.classList.remove('active');
                }
                favBtn.setAttribute('onclick', `handleToggleFavorite('${symbol}', ${newStatus})`);
            }
        }
    } catch (err) {
        console.error(`Failed to toggle favorite for ${symbol}:`, err);
        alert(`Error: ${err.message}`);
    }
}



/**
 * Handles deletion of an instrument.
 */
async function handleDeleteInstrument(symbol) {
    if (!confirm(`Are you sure you want to delete the instrument: ${symbol}?`)) {
        return;
    }

    try {
        const result = await deleteInstrument(symbol);
        alert(result.message || `${symbol} deleted successfully.`);
        loadInstrumentsManagerTable();
    } catch (err) {
        console.error(`Failed to delete ${symbol}:`, err);
        alert(`Error: ${err.message}`);
    }
}
