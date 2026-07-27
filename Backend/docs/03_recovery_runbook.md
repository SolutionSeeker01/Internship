# 3. Recovery Runbook

## 3.1 Overview
The `StartupRecoveryService` provides fail-safe, crash-resilient initialization upon application startup. It guarantees that any active or in-flight trades interrupted by a system crash, restart, or network partition are reconciled against actual broker exchange states without duplicate order submissions, state corruption, or lost trailing stop levels.

---

## 3.2 Startup Recovery Sequence

```
[ Application Startup ]
          │
          ▼
┌────────────────────────────────────────┐
│  StartupRecoveryService.execute()      │
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│  Fetch all OPEN / PARTIALLY_CLOSED     │
│  trades from TradeRepository           │
└──────────────────┬─────────────────────┘
                   │
                   ▼ Loop for each active trade
┌────────────────────────────────────────┐
│  Fetch Entry Order & Child Orders      │
│  from OrderRepository                  │
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│  reconstruct_position_state()          │
│  (Pure deterministic derivation)       │
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│  _reconcile_in_flight_trade_state()    │
│  (Query Broker REST API for pending)   │
└──────────────────┬─────────────────────┘
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
    Is CLOSED?        Is ACTIVE?
         │                   │
         ▼                   ▼
   Skip Registry     Register Trade ID in
   Update DB         OrderManagerRegistry
```

---

## 3.3 Crash Recovery Decision Tree

```
                      ┌─────────────────────────────────┐
                      │ Position State at Crash / Start │
                      └────────────────┬────────────────┘
                                       │
      ┌────────────────────────────────┼────────────────────────────────┐
      ▼                                ▼                                ▼
┌───────────┐                ┌───────────────────┐             ┌────────────────┐
│ PROTECTED │                │ SL_CANCEL_PENDING │             │  EXIT_PENDING  │
└─────┬─────┘                └─────────┬─────────┘             └───────┬────────┘
      │                                │                               │
      ▼                                ▼                               ▼
Query Broker SL                Query Broker SL                 Query Broker Exit
Order Status                   Order Status                    Order Status
      │                                │                               │
 ┌────┴─────┐                     ┌────┴───────────────┐          ┌────┴─────┐
 ▼          ▼                     ▼                    ▼          ▼          ▼
OPEN      FILLED              CANCELLED/            FILLED      FILLED    REJECTED/
 │          │                  REJECTED                │          │         NONE
 ▼          ▼                     │                    ▼          ▼          │
Maintain  Mark Trade              ▼                Mark Trade Mark Trade     ▼
BROKER_   CLOSED             Transition to           CLOSED     CLOSED   Revert to
PROTECTED                    SOFTWARE_TRAILING                           SOFTWARE_
                             ACTIVE & ratchet SL                         TRAILING_
                                                                         ACTIVE
```

---

## 3.4 Broker Reconciliation Flow

For any in-flight pending state (`SL_CANCEL_PENDING`, `TARGET_ORDER_PENDING`, `EXIT_PENDING`), recovery **MUST NEVER ASSUME** local state. It queries the broker REST API using `get_order_history(broker_order_id)`:

1. **`SL_CANCEL_PENDING` Reconciliation**:
   - If broker status is `CANCELLED` or `REJECTED`: The hard SL is confirmed gone. Update DB to `position_state="SOFTWARE_TRAILING_ACTIVE"`, populate `active_trailing_sl` with preserved trailing/intended SL level, update child order status to `CANCELLED`.
   - If broker status is `FILLED`: The hard broker SL executed before cancellation completed. Mark trade `status="CLOSED"`, `position_state="CLOSED"`.

2. **`EXIT_PENDING` Reconciliation**:
   - If broker status is `FILLED` or `COMPLETE`: The market exit succeeded while offline. Update DB to `status="CLOSED"`, `position_state="CLOSED"`.
   - If broker status is `REJECTED` or Order Not Found: The exit failed. Revert DB to `position_state="SOFTWARE_TRAILING_ACTIVE"` so the next incoming market tick immediately triggers a fresh market exit order.

3. **`TARGET_ORDER_PENDING` Reconciliation**:
   - If broker status is `FILLED` or `COMPLETE`: Target filled offline. Credit realized quantity, update `remaining_quantity`, set trade status to `PARTIALLY_CLOSED`, and transition `position_state` to `SOFTWARE_TRAILING_ACTIVE`.
   - If broker status is `CANCELLED`: Target order cancelled. Revert to `SOFTWARE_TRAILING_ACTIVE`.

---

## 3.5 Callback Reconciliation & Idempotency

- **Duplicate Ticks**: Incoming tick processing evaluates `active_trailing_sl`. If current tick LTP ratchets SL up, DB update is throttled to execute only when `active_trailing_sl` changes by `> 0.0001` or position state transitions.
- **Duplicate Callbacks**: Order update webhooks contain `idempotency_key`. `OrderRepository.update_order()` checks if order status is already `COMPLETE` or `CANCELLED` prior to processing, avoiding duplicate fill processing or quantity double-counting.
- **Duplicate Exits**: When an exit order is placed, `position_state` transitions synchronously to `EXIT_PENDING` before network transmission. Subsequent ticks while `EXIT_PENDING` is active skip exit placement.
