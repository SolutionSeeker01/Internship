/* =============================================================
   signal-monitor.js  —  Signal Monitor page controller
   Consumes: GET /signals/accepted
   ============================================================= */

'use strict';

console.info('[SignalMonitor] Module loaded.');

// ── Helpers ──────────────────────────────────────────────────

function getAuthHeaders() {
    const token = localStorage.getItem('access_token');
    return token ? { 'Authorization': `Bearer ${token}` } : {};
}

/**
 * Format an ISO timestamp string into a readable local time.
 * e.g. "2026-07-13T14:05:22" → "13 Jul, 02:05 PM"
 */
function formatTime(isoString) {
    if (!isoString) return '—';
    try {
        const d = new Date(isoString);
        return d.toLocaleString([], {
            day: '2-digit',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit',
            hour12: true
        });
    } catch {
        return isoString;
    }
}

/**
 * Format a numeric price to fixed 2 decimal places.
 */
function formatPrice(val) {
    if (val === null || val === undefined) return '—';
    return parseFloat(val).toFixed(2);
}

/**
 * Build an action badge HTML string.
 */
function actionBadge(action) {
    const cls = (action === 'BUY') ? 'buy' : 'sell';
    return `<span class="action-badge ${cls}">${action}</span>`;
}

/**
 * Build a status badge HTML string.
 */
function statusBadge(status) {
    const map = {
        PENDING:   'pending',
        COMPLETED: 'completed',
        CANCELLED: 'cancelled',
    };
    const cls = map[status] || 'pending';
    return `<span class="status-badge ${cls}">${status}</span>`;
}

/**
 * Build a validation badge HTML string.
 */
function valBadge(valStatus) {
    const map = {
        VALIDATED: 'validated',
        PARTIAL:   'partial',
    };
    const cls = map[valStatus] || 'validated';
    return `<span class="val-badge ${cls}">${valStatus}</span>`;
}

// ── Render ────────────────────────────────────────────────────

function renderSignals(signals) {
    const tbody = document.getElementById('signals-table-body');
    const countBadge = document.getElementById('signal-count-badge');

    if (!tbody) return;

    countBadge.textContent = `${signals.length} signal${signals.length !== 1 ? 's' : ''}`;

    if (signals.length === 0) {
        tbody.innerHTML = `
            <tr class="state-row">
                <td colspan="13">
                    <span class="state-icon">📭</span>
                    <div class="state-title">No accepted signals yet</div>
                    <div class="state-description">Accepted signals will appear here once the webhook receives a valid trading alert.</div>
                </td>
            </tr>`;
        return;
    }

    tbody.innerHTML = signals.map(s => `
        <tr>
            <td class="col-time">${formatTime(s.created_at)}</td>
            <td><strong>${s.symbol}</strong></td>
            <td>${actionBadge(s.action)}</td>
            <td><span class="tf-chip">${s.timeframe}</span></td>
            <td class="text-right col-numeric">${formatPrice(s.entry)}</td>
            <td class="text-right col-numeric">${formatPrice(s.stoploss)}</td>
            <td class="text-right col-target">${formatPrice(s.t1)}</td>
            <td class="text-right col-target">${formatPrice(s.t2)}</td>
            <td class="text-right col-target">${formatPrice(s.t3)}</td>
            <td>${statusBadge(s.status)}</td>
            <td>${valBadge(s.validation_status)}</td>
            <td style="font-family: monospace; font-weight: 600; text-align: center;">${s.strategy_id !== null && s.strategy_id !== undefined ? s.strategy_id : '—'}</td>
            <td class="text-right col-id">#${s.id}</td>
        </tr>
    `).join('');
}

function renderLoading() {
    const tbody = document.getElementById('signals-table-body');
    if (!tbody) return;
    tbody.innerHTML = `
        <tr class="state-row loading">
            <td colspan="13">
                <span class="state-icon">⏳</span>
                <div class="state-title">Loading signals...</div>
            </td>
        </tr>`;
}

function renderError(message) {
    const tbody = document.getElementById('signals-table-body');
    const countBadge = document.getElementById('signal-count-badge');
    if (!tbody) return;
    if (countBadge) countBadge.textContent = 'Error';
    tbody.innerHTML = `
        <tr class="state-row">
            <td colspan="13">
                <span class="state-icon">⚠️</span>
                <div class="state-title">Failed to load signals</div>
                <div class="state-description">${message}</div>
            </td>
        </tr>`;
}

// ── Data Fetch ────────────────────────────────────────────────

async function loadSignals(isSilent = false) {
    if (!isSilent) {
        renderLoading();
    }
    const refreshBtn = document.getElementById('btn-refresh');
    if (refreshBtn && !isSilent) {
        refreshBtn.classList.add('spinning');
        refreshBtn.disabled = true;
    }

    try {
        const response = await fetch(`${window.API_BASE_URL}/signals/accepted?limit=50&offset=0`, {
            cache: 'no-store',
            headers: getAuthHeaders()
        });

        if (response.status === 401) {
            window.location.replace('login.html');
            return;
        }

        if (response.status === 403) {
            renderError('Access denied. Only MASTER users can view the Signal Monitor.');
            return;
        }

        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            if (!isSilent) {
                renderError(body.detail || `Server error (${response.status})`);
            }
            return;
        }

        const signals = await response.json();
        renderSignals(signals);

    } catch (err) {
        console.error('[SignalMonitor] Fetch error:', err);
        if (!isSilent) {
            renderError('Could not reach the backend. Check your network connection.');
        }
    } finally {
        if (refreshBtn && !isSilent) {
            refreshBtn.classList.remove('spinning');
            refreshBtn.disabled = false;
        }
    }
}

// ── Init ──────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    const refreshBtn = document.getElementById('btn-refresh');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => loadSignals(false));
    }
    loadSignals(false);
    
    // Set up silent polling every 5 seconds
    setInterval(() => loadSignals(true), 5000);
});
