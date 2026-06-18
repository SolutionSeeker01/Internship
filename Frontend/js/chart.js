/* =============================================================
   chart.js  –  TradingView Lightweight Charts management
   ============================================================= */

'use strict';

console.info("[Chart] Module loaded.");

/** @type {any} */
let chart;
/** @type {any} */
let candleSeries;
let selectedSymbol = "RELIANCE";
let selectedInterval = "minute";
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
                const options = { timeZone: 'Asia/Kolkata' };
                
                if (tickMarkType === 0) { // Year
                    options.year = 'numeric';
                    return date.toLocaleDateString('en-US', options);
                } else if (tickMarkType === 1) { // Month
                    options.month = 'short';
                    return date.toLocaleDateString('en-US', options);
                } else if (tickMarkType === 2) { // DayOfMonth
                    options.day = 'numeric';
                    options.month = 'short';
                    return date.toLocaleDateString('en-US', options);
                } else { // Time or TimeWithSeconds
                    options.hour = '2-digit';
                    options.minute = '2-digit';
                    options.hour12 = false;
                    return date.toLocaleTimeString('en-US', options);
                }
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

async function loadCandles(symbol, interval = selectedInterval) {
    selectedSymbol = symbol;
    selectedInterval = interval;
    lastCumulativeVolume = null; // Reset volume accumulator for the new symbol
    
    // Update chart title dynamically
    const intervalLabels = {
        "minute": "1 Minute",
        "3minute": "3 Minute",
        "5minute": "5 Minute",
        "15minute": "15 Minute",
        "30minute": "30 Minute",
        "60minute": "1 Hour",
        "day": "Daily"
    };
    const label = intervalLabels[interval] || "1 Minute";
    const titleEl = getEl("chart-title");
    if (titleEl) {
        titleEl.textContent = `${symbol} - ${label} Candles`;
    }

    // Update timeframe buttons active state to match
    document.querySelectorAll(".timeframe-btn").forEach(btn => {
        if (btn.getAttribute("data-interval") === interval) {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });

    // Update row highlighting
    document.querySelectorAll(".stock-row").forEach(row => {
        if (row.getAttribute("data-symbol") === symbol) {
            row.classList.add("selected-row");
        } else {
            row.classList.remove("selected-row");
        }
    });

    try {
        const data = await getCandles(symbol, interval, 100);
        
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

    // Determine interval duration in seconds
    let intervalSeconds = 60;
    if (selectedInterval === "3minute") intervalSeconds = 180;
    else if (selectedInterval === "5minute") intervalSeconds = 300;
    else if (selectedInterval === "15minute") intervalSeconds = 900;
    else if (selectedInterval === "30minute") intervalSeconds = 1800;
    else if (selectedInterval === "60minute") intervalSeconds = 3600;
    else if (selectedInterval === "day") intervalSeconds = 86400;

    // Truncate to the start of the current interval (in local seconds)
    const intervalStartSeconds = Math.floor(tickSeconds / intervalSeconds) * intervalSeconds;

    const tickVolume = Number(data.volume) || 0;
    let volumeDiff = 0;
    if (lastCumulativeVolume !== null) {
        volumeDiff = Math.max(0, tickVolume - lastCumulativeVolume);
    }
    lastCumulativeVolume = tickVolume;

    if (currentCandles.length === 0) {
        const firstCandle = {
            time: intervalStartSeconds,
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

    if (intervalStartSeconds === lastCandle.time) {
        // Update the active candle
        lastCandle.close = Number(data.ltp);
        if (Number(data.ltp) > lastCandle.high) lastCandle.high = Number(data.ltp);
        if (Number(data.ltp) < lastCandle.low) lastCandle.low = Number(data.ltp);
        lastCandle.volume = (lastCandle.volume || 0) + volumeDiff;

        candleSeries.update(lastCandle);
        chart.timeScale().scrollToRealTime();
    } else if (intervalStartSeconds > lastCandle.time) {
        // Roll over and create a new active candle
        const newCandle = {
            time: intervalStartSeconds,
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
