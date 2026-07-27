# 6. Operational Runbook

## 6.1 Overview
This runbook describes Day-2 operational procedures for managing, monitoring, troubleshooting, and diagnosing the Software-Managed Trailing Stop-Loss service in production.

---

## 6.2 Standard Operating Procedures (SOPs)

### **SOP 1: Service Restart Procedure**
When restarting the trading engine backend:
1. Verify market status (ensure restart occurs during low-volatility or pre-market if possible).
2. Issue graceful shutdown signal (`SIGTERM`) to allow active tick processing to flush.
3. Start backend service:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```
4. **Verify Startup Recovery**: Inspect application logs immediately after launch for Phase 6 Recovery execution:
   ```text
   INFO: Starting StartupRecoveryService...
   INFO: Found N active trades for recovery reconciliation.
   INFO: Phase 6 Recovery: Reconciled trade ID 101 -> SOFTWARE_TRAILING_ACTIVE
   INFO: StartupRecoveryService complete. N trades registered in OrderManagerRegistry.
   ```

---

### **SOP 2: Handling Broker Outages & Disconnections**
If Zerodha / Broker API connection drops:
1. System logs error `BrokerAdapterException` or connection timeout.
2. In-memory `active_trailing_sl` thresholds **remain intact and continue ratcheting** on incoming market ticks.
3. If market price breaches `active_trailing_sl` during a broker outage:
   - Order placement fails and trade state transitions to `EXIT_ORDER_REJECTED` or reverts to `SOFTWARE_TRAILING_ACTIVE`.
   - On the next valid tick post-reconnection, the software automatically retries submitting the market exit order (`EXIT_ALL`).

---

### **SOP 3: Investigating Failed Exits**
If a trade fails to exit after a software trailing SL breach:
1. Search application logs for `EXIT_ORDER_REJECTED` or `Software exit submission failed`:
   ```bash
   grep -E "EXIT_ORDER_REJECTED|Software exit" /var/log/trading_backend.log
   ```
2. Check order repository for the generated child order with `order_role="EXIT_ALL"`.
3. Check broker account margins or token expiration errors.
4. **Manual Trigger**: If broker rejected order due to price band/circuit limits, execute exit manually via Broker web terminal and update trade state in DB:
   ```sql
   UPDATE trades SET status = 'CLOSED', position_state = 'CLOSED' WHERE id = <TRADE_ID>;
   ```

---

### **SOP 4: Diagnosing Stuck Trades**
If a trade appears unresponsive to market price movements:
1. **Verify Registry Membership**: Check if the trade ID is registered in `OrderManagerRegistry`:
   - If missing from registry, execute a manual recovery scan or restart the service.
2. **Inspect Invariant Violations**: Check if trade is stuck in a transient state (`SL_CANCEL_PENDING`, `EXIT_PENDING`, `TARGET_ORDER_PENDING`):
   ```sql
   SELECT id, status, position_state, active_trailing_sl, trailing_sl_activated 
   FROM trades 
   WHERE status IN ('OPEN', 'PARTIALLY_CLOSED');
   ```
3. If stuck in `SL_CANCEL_PENDING`, check Zerodha web UI to confirm whether broker SL `SL-xxx` is truly cancelled or open.
