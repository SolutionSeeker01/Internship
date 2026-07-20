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
        <tr class="clickable-row" data-signal-id="${s.id}" style="cursor: pointer;">
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

// ── Signal Details Modal & Rendering ──────────────────────────

const modalOverlay = document.getElementById('signal-details-modal');
const modalContent = document.getElementById('modal-details-content');
const closeModalBtn = document.getElementById('close-modal-btn');

function showModal() {
    if (modalOverlay) modalOverlay.style.display = 'flex';
}

function hideModal() {
    if (modalOverlay) modalOverlay.style.display = 'none';
}

if (closeModalBtn) {
    closeModalBtn.addEventListener('click', hideModal);
}

// Close modal when clicking outside the card
if (modalOverlay) {
    modalOverlay.addEventListener('click', (e) => {
        if (e.target === modalOverlay) hideModal();
    });
}

function renderModalDetails(details) {
    const s = details.signal;
    const summary = details.summary;
    const targets = details.targets;

    const actionClass = s.action === 'BUY' ? 'buy' : 'sell';

    let targetsHTML = '';
    if (targets.length === 0) {
        targetsHTML = `
            <div class="empty-state" style="text-align: center; padding: 24px; color: var(--text-secondary);">
                <span>📭</span>
                <p style="margin: 8px 0 0 0; font-size: 13px;">No clients targeted for this signal.</p>
            </div>
        `;
    } else {
        targetsHTML = `
            <div class="table-responsive" style="margin-top: 16px;">
                <table class="signals-table" style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr>
                            <th scope="col" style="text-align: left;">Username</th>
                            <th scope="col" style="text-align: left;">Status</th>
                            <th scope="col" style="text-align: left;">Reason / Details</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${targets.map(t => {
                            const badgeClass = t.status === 'READY' ? 'badge-success' : 'badge-danger';
                            const reasonText = t.skip_reason ? t.skip_reason : '—';
                            return `
                                <tr>
                                    <td style="font-weight: 600;">${t.username}</td>
                                    <td><span class="info-badge ${badgeClass}">${t.status}</span></td>
                                    <td style="color: var(--text-secondary); font-family: monospace; font-size: 11px;">${reasonText}</td>
                                </tr>
                            `;
                        }).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    modalContent.innerHTML = `
        <!-- Signal Canonical Info -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; margin-bottom: 20px; padding: 12px; background: var(--bg-body); border-radius: var(--radius-md); border: 1px solid var(--border-color);">
            <div>
                <div style="font-size: 10px; font-weight: 700; color: var(--text-secondary); text-transform: uppercase;">Symbol</div>
                <div style="font-size: 14px; font-weight: 700; margin-top: 2px;">${s.symbol}</div>
            </div>
            <div>
                <div style="font-size: 10px; font-weight: 700; color: var(--text-secondary); text-transform: uppercase;">Action</div>
                <div style="margin-top: 2px;"><span class="action-badge ${actionClass}">${s.action}</span></div>
            </div>
            <div>
                <div style="font-size: 10px; font-weight: 700; color: var(--text-secondary); text-transform: uppercase;">Timeframe</div>
                <div style="font-size: 14px; font-weight: 600; margin-top: 2px;"><span class="tf-chip">${s.timeframe}</span></div>
            </div>
            <div>
                <div style="font-size: 10px; font-weight: 700; color: var(--text-secondary); text-transform: uppercase;">Entry Price</div>
                <div style="font-size: 14px; font-weight: 700; margin-top: 2px; font-variant-numeric: tabular-nums;">₹${formatPrice(s.entry)}</div>
            </div>
            <div>
                <div style="font-size: 10px; font-weight: 700; color: var(--text-secondary); text-transform: uppercase;">Stop Loss</div>
                <div style="font-size: 14px; font-weight: 700; margin-top: 2px; color: var(--color-negative); font-variant-numeric: tabular-nums;">₹${formatPrice(s.stoploss)}</div>
            </div>
        </div>

        <!-- Summary Statistics Cards -->
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px;">
            <div style="background: var(--bg-card); border: 1px solid var(--border-color); padding: 12px; border-radius: var(--radius-md); text-align: center; box-shadow: var(--shadow-premium);">
                <div style="font-size: 10px; font-weight: 700; color: var(--text-secondary); text-transform: uppercase;">Total Targeted</div>
                <div style="font-size: 20px; font-weight: 700; margin-top: 4px; color: var(--text-primary);">${summary.total}</div>
            </div>
            <div style="background: var(--bg-card); border: 1px solid var(--border-color); padding: 12px; border-radius: var(--radius-md); text-align: center; box-shadow: var(--shadow-premium);">
                <div style="font-size: 10px; font-weight: 700; color: var(--text-secondary); text-transform: uppercase; color: var(--color-positive);">Ready</div>
                <div style="font-size: 20px; font-weight: 700; margin-top: 4px; color: var(--color-positive);">${summary.ready}</div>
            </div>
            <div style="background: var(--bg-card); border: 1px solid var(--border-color); padding: 12px; border-radius: var(--radius-md); text-align: center; box-shadow: var(--shadow-premium);">
                <div style="font-size: 10px; font-weight: 700; color: var(--text-secondary); text-transform: uppercase; color: var(--color-negative);">Skipped</div>
                <div style="font-size: 20px; font-weight: 700; margin-top: 4px; color: var(--color-negative);">${summary.skipped}</div>
            </div>
        </div>

        <!-- Execution Targets Header & Unified Table -->
        <h4 style="margin: 0; font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-secondary);">Client Targets Status</h4>
        ${targetsHTML}
    `;
}

async function loadSignalDetails(signalId) {
    showModal();
    if (modalContent) {
        modalContent.innerHTML = `
            <div style="text-align: center; padding: 48px 0; color: var(--text-secondary);">
                <div class="refresh-btn spinning" style="font-size: 28px; display: inline-block;">↻</div>
                <p style="margin: 12px 0 0 0; font-size: 13px;">Fetching signal targets details...</p>
            </div>
        `;
    }

    try {
        const response = await fetch(`${window.API_BASE_URL}/signals/${signalId}/details`, {
            cache: 'no-store',
            headers: getAuthHeaders()
        });

        if (response.status === 401) {
            window.location.replace('login.html');
            return;
        }

        if (response.status === 403) {
            if (modalContent) {
                modalContent.innerHTML = `
                    <div style="text-align: center; padding: 24px; color: var(--color-negative);">
                        <span>⚠️</span>
                        <p style="margin: 8px 0 0 0; font-weight: 600;">Access Denied. Only MASTER accounts can view target details.</p>
                    </div>
                `;
            }
            return;
        }

        if (!response.ok) {
            if (modalContent) {
                modalContent.innerHTML = `
                    <div style="text-align: center; padding: 24px; color: var(--color-negative);">
                        <span>⚠️</span>
                        <p style="margin: 8px 0 0 0; font-weight: 600;">Failed to load details (${response.status})</p>
                    </div>
                `;
            }
            return;
        }

        const details = await response.json();
        renderModalDetails(details);

    } catch (err) {
        console.error('[SignalMonitor] Details fetch error:', err);
        if (modalContent) {
            modalContent.innerHTML = `
                <div style="text-align: center; padding: 24px; color: var(--color-negative);">
                    <span>⚠️</span>
                    <p style="margin: 8px 0 0 0; font-weight: 600;">Error connecting to server. Please try again.</p>
                </div>
            `;
        }
    }
}

// ── Init ──────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    const refreshBtn = document.getElementById('btn-refresh');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => loadSignals(false));
    }

    // Attach delegated click listener to table row elements in the signals table
    const tableBody = document.getElementById('signals-table-body');
    if (tableBody) {
        tableBody.addEventListener('click', (e) => {
            const row = e.target.closest('.clickable-row');
            if (row) {
                const signalId = row.getAttribute('data-signal-id');
                if (signalId) {
                    loadSignalDetails(signalId);
                }
            }
        });
    }

    loadSignals(false);
    
    // Set up silent polling every 5 seconds
    setInterval(() => loadSignals(true), 5000);
});
