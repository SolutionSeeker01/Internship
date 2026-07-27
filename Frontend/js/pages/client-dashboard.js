// client-dashboard.js - Client Portfolio Dashboard Controller (REST Mode)
'use strict';

console.info("[Client Dashboard] REST controller initialized.");

document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Elements ---
    const elConnectionDot = document.getElementById('connection-status-dot');
    const elConnectionText = document.getElementById('connection-status-text');
    const elTodayPnL = document.getElementById('card-today-pnl');
    const elAvailableCash = document.getElementById('card-available-cash');
    const elUtilizedMargin = document.getElementById('card-utilized-margin');
    const elMarginUtilization = document.getElementById('card-margin-utilization');
    const elDailyDrawdown = document.getElementById('card-daily-drawdown');
    const elRiskStatus = document.getElementById('card-risk-status');
    const elAutoTrading = document.getElementById('widget-auto-trading');
    const elActiveStrategies = document.getElementById('widget-active-strategies');
    const elDisabledStrategies = document.getElementById('widget-disabled-strategies');
    const elMaxDrawdown = document.getElementById('widget-max-drawdown');
    const elCurrentDrawdown = document.getElementById('widget-current-drawdown');
    const positionsTableBody = document.getElementById('positions-table-body');
    const elLastUpdated = document.getElementById('last-updated-time');

    // --- Helper Formatting Utils ---
    const formatCurrency = (val) => {
        return new Intl.NumberFormat('en-IN', {
            style: 'currency',
            currency: 'INR',
            minimumFractionDigits: 2
        }).format(val);
    };

    const formatPct = (val) => {
        return `${val.toFixed(2)}%`;
    };

    // --- Update Header Status Indicator ---
    function updateConnectionStatus(statusName) {
        const isConnected = statusName === 'CONNECTED';
        
        if (elConnectionDot) {
            elConnectionDot.classList.toggle('connected', isConnected);
            elConnectionDot.classList.toggle('disconnected', !isConnected);
        }
        if (elConnectionText) {
            elConnectionText.textContent = statusName;
            elConnectionText.style.color = isConnected ? 'var(--color-positive)' : 'var(--color-negative)';
        }
    }

    // --- API Integration Calls ---
    async function loadDashboardSummary() {
        const accessToken = localStorage.getItem('access_token');
        if (!accessToken) {
            updateConnectionStatus('SESSION EXPIRED');
            return;
        }

        try {
            const response = await fetch(`${window.API_BASE_URL}/api/v1/client/dashboard/summary`, {
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                if (response.status === 401 || response.status === 400) {
                    updateConnectionStatus('SESSION EXPIRED');
                } else {
                    updateConnectionStatus('OFFLINE');
                }
                return;
            }

            const summary = await response.json();
            
            // 1. Connection states
            updateConnectionStatus(summary.connection_status);

            // 2. Metrics card rendering
            if (elTodayPnL) {
                const formattedVal = formatCurrency(summary.today_pnl);
                elTodayPnL.textContent = summary.today_pnl >= 0 ? `+${formattedVal}` : formattedVal;
                elTodayPnL.style.color = summary.today_pnl >= 0 ? 'var(--color-positive)' : 'var(--color-negative)';
            }

            if (elAvailableCash) elAvailableCash.textContent = formatCurrency(summary.net_value ?? summary.net_cash ?? summary.capital_base ?? summary.available_cash);
            if (elUtilizedMargin) elUtilizedMargin.textContent = formatCurrency(summary.utilized_margin);
            if (elMarginUtilization) elMarginUtilization.textContent = formatPct(summary.margin_utilization_pct);
            if (elDailyDrawdown) elDailyDrawdown.textContent = formatPct(summary.daily_drawdown_pct);
            
            if (elRiskStatus) {
                elRiskStatus.textContent = summary.risk_status;
                elRiskStatus.style.color = summary.risk_status === 'SAFE' ? 'var(--color-positive)' : 'var(--color-negative)';
            }

            if (elAutoTrading) {
                elAutoTrading.textContent = summary.auto_trading_enabled ? 'Enabled' : 'Disabled';
                elAutoTrading.className = `info-badge ${summary.auto_trading_enabled ? 'badge-success' : 'badge-danger'}`;
            }

            if (elActiveStrategies) elActiveStrategies.textContent = summary.active_strategies;
            if (elDisabledStrategies) elDisabledStrategies.textContent = summary.disabled_strategies;
            if (elMaxDrawdown) elMaxDrawdown.textContent = formatPct(summary.max_drawdown_limit_pct);
            
            if (elCurrentDrawdown) {
                elCurrentDrawdown.textContent = formatPct(summary.daily_drawdown_pct);
                elCurrentDrawdown.style.color = summary.daily_drawdown_pct < summary.max_drawdown_limit_pct ? 'var(--color-positive)' : 'var(--color-negative)';
            }

        } catch (error) {
            console.error("Failed to load dashboard summary metrics:", error);
            updateConnectionStatus('SESSION EXPIRED');
        }
    }

    async function loadPortfolioPositions() {
        const accessToken = localStorage.getItem('access_token');
        if (!accessToken) return;

        try {
            const response = await fetch(`${window.API_BASE_URL}/api/v1/client/portfolio/positions`, {
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) return;

            const data = await response.json();
            renderPositions(data.positions || []);
        } catch (error) {
            console.error("Failed to fetch positions from backend:", error);
        }
    }

    // --- Render Functions ---
    function renderPositions(positions) {
        if (!positionsTableBody) return;
        positionsTableBody.innerHTML = '';

        if (positions.length === 0) {
            positionsTableBody.innerHTML = `
                <tr>
                    <td colspan="8" class="text-center" style="color: var(--text-secondary); padding: 24px;">No active trading positions.</td>
                </tr>
            `;
            return;
        }

        positions.forEach(pos => {
            const tr = document.createElement('tr');
            
            const livePnLFormatted = formatCurrency(pos.unrealized_pnl);
            const livePnLClass = pos.unrealized_pnl >= 0 ? 'positive' : 'negative';

            tr.innerHTML = `
                <td style="font-weight: 600;">${pos.symbol}</td>
                <td style="color: var(--text-secondary);">${pos.strategy_name}</td>
                <td><span class="info-badge ${pos.direction === 'LONG' ? 'badge-success' : 'badge-danger'}">${pos.direction}</span></td>
                <td class="text-right">${pos.quantity}</td>
                <td class="text-right">${formatCurrency(pos.average_price)}</td>
                <td class="text-right" style="font-weight: 600;">${formatCurrency(pos.last_traded_price)}</td>
                <td class="text-right" style="color: var(--color-negative);">${formatCurrency(pos.stop_loss_price)}</td>
                <td class="text-right ${livePnLClass}" style="font-weight: 600;">
                    ${pos.unrealized_pnl >= 0 ? '+' : ''}${livePnLFormatted}
                </td>
            `;
            positionsTableBody.appendChild(tr);
        });
    }

    function updateLastUpdatedTime() {
        if (elLastUpdated) {
            const now = new Date();
            elLastUpdated.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
        }
    }

    // --- Execution ---
    async function loadAllData() {
        await loadDashboardSummary();
        await loadPortfolioPositions();
        updateLastUpdatedTime();
    }

    loadAllData();
});
