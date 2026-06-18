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
async function getCandles(symbol, interval, limit = 100) {
    const url = `http://127.0.0.1:8000/candles/${symbol}?interval=${interval}&limit=${limit}`;
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`Failed to fetch candles: ${response.status}`);
    }
    return await response.json();
}

/**
 * Placeholders for future instrument manager integration.
 */
async function getInstruments() {
    console.log("getInstruments placeholder called");
    return [];
}

async function createInstrument(instrumentData) {
    console.log("createInstrument placeholder called", instrumentData);
    return { success: true };
}

async function deleteInstrument(instrumentId) {
    console.log("deleteInstrument placeholder called", instrumentId);
    return { success: true };
}
