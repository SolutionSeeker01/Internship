/* =============================================================
   api.js  –  API requests wrappers
   ============================================================= */

'use strict';

/**
 * Fetches historical candlestick data from the backend.
 * 
 * @param {string} symbol - Trading asset symbol.
 * @param {string} interval - Time interval.
 * @param {number} limit - Maximum number of candles.
 * @returns {Promise<Array>} Promise resolving to candle list.
 */
async function getCandles(symbol, interval, limit = 100, exchange = null) {
    let url = `http://127.0.0.1:8000/candles/${symbol}?interval=${interval}&limit=${limit}`;
    if (exchange) {
        url += `&exchange=${exchange}`;
    }
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) {
        throw new Error(`Failed to fetch candles: ${response.status}`);
    }
    return await response.json();
}

/**
 * Fetches all instruments from the backend database.
 * @returns {Promise<Array>}
 */
async function getInstruments() {
    const response = await fetch("http://127.0.0.1:8000/instruments", { cache: 'no-store' });
    if (!response.ok) {
        throw new Error(`Failed to fetch instruments: ${response.status}`);
    }
    return await response.json();
}

/**
 * Searches instruments by query q and optional limit.
 * @param {string} q
 * @param {number} limit
 * @returns {Promise<Array>}
 */
async function searchInstruments(q, limit = 20) {
    const response = await fetch(`http://127.0.0.1:8000/instruments/search?q=${encodeURIComponent(q)}&limit=${limit}`, { cache: 'no-store' });
    if (!response.ok) {
        throw new Error(`Failed to search instruments: ${response.status}`);
    }
    return await response.json();
}


/**
 * Creates a new instrument via POST.
 * @param {object} instrumentData 
 * @returns {Promise<object>}
 */
async function createInstrument(instrumentData) {
    const response = await fetch("http://127.0.0.1:8000/instruments", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(instrumentData)
    });
    if (!response.ok) {
        const errorDetail = await response.json();
        throw new Error(errorDetail.detail || `Failed to create instrument: ${response.status}`);
    }
    return await response.json();
}

/**
 * Deletes an instrument by symbol.
 * @param {string} symbol 
 * @returns {Promise<object>}
 */
async function deleteInstrument(symbol, exchange) {
    if (!exchange) throw new Error("Exchange is mandatory to delete an instrument.");
    const response = await fetch(`http://127.0.0.1:8000/instruments/${symbol}?exchange=${encodeURIComponent(exchange)}`, {
        method: "DELETE"
    });
    if (!response.ok) {
        const errorDetail = await response.json();
        throw new Error(errorDetail.detail || `Failed to delete instrument: ${response.status}`);
    }
    return await response.json();
}

/**
 * Toggles the favorite status of an instrument.
 * @param {string} symbol 
 * @param {boolean} isFavorite 
 * @returns {Promise<object>}
 */
async function toggleInstrumentFavorite(symbol, exchange, isFavorite) {
    if (!exchange) throw new Error("Exchange is mandatory to toggle favorite status.");
    const response = await fetch(`http://127.0.0.1:8000/instruments/${symbol}/favorite?exchange=${encodeURIComponent(exchange)}`, {
        method: "PATCH",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ is_favorite: isFavorite })
    });
    if (!response.ok) {
        const errorDetail = await response.json();
        throw new Error(errorDetail.detail || `Failed to toggle favorite: ${response.status}`);
    }
    return await response.json();
}



/**
 * Fetches only favorite active instruments.
 * @returns {Promise<Array>}
 */
async function getFavoriteInstruments() {
    const response = await fetch("http://127.0.0.1:8000/instruments/favorites", { cache: 'no-store' });
    if (!response.ok) {
        throw new Error(`Failed to fetch favorite instruments: ${response.status}`);
    }
    return await response.json();
}

/**
 * Fetches the dashboard watchlist with independent favorite/fallback logic.
 * Returns { indices: [], stocks: [], view_mode: { indices: string, stocks: string } }
 * @returns {Promise<object>}
 */
async function getDashboardWatchlist() {
    const response = await fetch("http://127.0.0.1:8000/dashboard/watchlist", { cache: 'no-store' });
    if (!response.ok) {
        throw new Error(`Failed to fetch dashboard watchlist: ${response.status}`);
    }
    return await response.json();
}

/**
 * Syncs instruments from Zerodha master list with exchange and segment filters.
 * @param {string[]} exchanges
 * @param {string[]} segments
 * @returns {Promise<object>}
 */
async function syncInstruments(exchanges, segments) {
    const response = await fetch("http://127.0.0.1:8000/instruments/sync", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ exchanges, segments })
    });
    if (!response.ok) {
        const errorDetail = await response.json();
        throw new Error(errorDetail.detail || `Failed to sync instruments: ${response.status}`);
    }
    return await response.json();
}

/**
 * Clears all instruments from the database.
 * @returns {Promise<object>}
 */
async function clearAllInstruments() {
    const response = await fetch("http://127.0.0.1:8000/instruments/all", {
        method: "DELETE"
    });
    if (!response.ok) {
        const errorDetail = await response.json();
        throw new Error(errorDetail.detail || `Failed to clear all instruments: ${response.status}`);
    }
    return await response.json();
}
