/* =============================================================
   rejected-signals.js  —  Rejected Signals audit log controller
   Consumes: GET /signals/rejected
   ============================================================= */

'use strict';

console.info('[RejectedSignals] Module loaded.');

// ── Helpers ──────────────────────────────────────────────────

function getAuthHeaders() {
    const token = localStorage.getItem('access_token');
    return token ? { 'Authorization': `Bearer ${token}` } : {};
}

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

function formatPrice(val) {
    if (val === null || val === undefined) return '—';
    return parseFloat(val).toFixed(2);
}

function actionBadge(action) {
    const cls = (action === 'BUY') ? 'buy' : 'sell';
    return `<span class="action-badge ${cls}">${action}</span>`;
}

// ── Render ────────────────────────────────────────────────────

function renderRejected(signals) {
    const tbody = document.getElementById('rejected-table-body');
    const countBadge = document.getElementById('signal-count-badge');

    if (!tbody) return;

    countBadge.textContent = `${signals.length} signal${signals.length !== 1 ? 's' : ''}`;

    if (signals.length === 0) {
        tbody.innerHTML = `
            <tr class="state-row">
                <td colspan="8">
                    <span class="state-icon">✅</span>
                    <div class="state-title">No rejected signals</div>
                    <div class="state-description">All received signals have passed validation. This audit log will show any that fail.</div>
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
            <td class="col-reason">${s.validation_reason || '—'}</td>
            <td><span class="val-badge" style="background:#fee2e2;color:#b91c1c;">${s.validation_status}</span></td>
            <td class="text-right col-id">#${s.id}</td>
        </tr>
    `).join('');
}

function renderLoading() {
    const tbody = document.getElementById('rejected-table-body');
    if (!tbody) return;
    tbody.innerHTML = `
        <tr class="state-row loading">
            <td colspan="8">
                <span class="state-icon">⏳</span>
                <div class="state-title">Loading rejected signals...</div>
            </td>
        </tr>`;
}

function renderError(message) {
    const tbody = document.getElementById('rejected-table-body');
    const countBadge = document.getElementById('signal-count-badge');
    if (!tbody) return;
    if (countBadge) countBadge.textContent = 'Error';
    tbody.innerHTML = `
        <tr class="state-row">
            <td colspan="8">
                <span class="state-icon">⚠️</span>
                <div class="state-title">Failed to load rejected signals</div>
                <div class="state-description">${message}</div>
            </td>
        </tr>`;
}

// ── Data Fetch ────────────────────────────────────────────────

async function loadRejectedSignals(isSilent = false) {
    if (!isSilent) {
        renderLoading();
    }
    const refreshBtn = document.getElementById('btn-refresh');
    if (refreshBtn && !isSilent) {
        refreshBtn.classList.add('spinning');
        refreshBtn.disabled = true;
    }

    try {
        const response = await fetch(`${window.API_BASE_URL}/signals/rejected?limit=50&offset=0`, {
            cache: 'no-store',
            headers: getAuthHeaders()
        });

        if (response.status === 401) {
            window.location.replace('login.html');
            return;
        }

        if (response.status === 403) {
            renderError('Access denied. Only MASTER users can view the rejected signals log.');
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
        renderRejected(signals);

    } catch (err) {
        console.error('[RejectedSignals] Fetch error:', err);
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
        refreshBtn.addEventListener('click', () => loadRejectedSignals(false));
    }
    loadRejectedSignals(false);
    
    // Set up silent polling every 5 seconds
    setInterval(() => loadRejectedSignals(true), 5000);
});
