# 7. Invariant Catalogue

## 7.1 Overview
Architectural Invariants are strict system assertions that must remain true across every state transition, database write, and execution phase. They protect against split-brain protection, double execution, lost trailing stops, and invalid database records.

---

## 7.2 Complete Invariant Roster

### **Invariant 1: Exclusive Stop-Loss Ownership**
- **Description**: A trade MUST NOT have both an active hard broker stop-loss order and an active software trailing stop-loss simultaneously.
- **Why it Exists**: Prevents double-liquidation where both the broker exchange SL and the software market exit fire for the same position quantity.
- **Where Enforced**: `PositionStateReconstructor`, `OrderManagerService`.
- **Consequences of Violation**: Position over-hedging or short-selling penalties on broker account.

---

### **Invariant 2: Monotonic Trailing SL Ratchet (Long Positions)**
- **Description**: `active_trailing_sl` for a BUY/Long position MUST NEVER decrease. It can only stay constant or ratchet upwards.
- **Why it Exists**: Ensures profit protection cannot be eroded during market retracements.
- **Where Enforced**: `TrailingStopEngine.calculate_new_stop_loss()`.
- **Consequences of Violation**: Sub-optimal exit execution and loss of secured unrealized gains.

---

### **Invariant 3: Handover Irreversibility**
- **Description**: Once `trailing_sl_activated` is set to `True` and state transitions to `SOFTWARE_TRAILING_ACTIVE`, state MUST NEVER revert to `BROKER_PROTECTED`.
- **Why it Exists**: Eliminates re-placing hard broker SL orders which are vulnerable to rejection or rate limits.
- **Where Enforced**: `PositionStateReconstructor`, `StartupRecoveryService`.
- **Consequences of Violation**: Re-introduction of legacy broker trailing order modification bugs.

---

### **Invariant 4: Software Trailing Active SL Absence**
- **Description**: If `position_state` is `SOFTWARE_TRAILING_ACTIVE`, no active child order with `order_role="STOPLOSS"` may exist with status `OPEN`, `SUBMITTED`, or `PLACED`.
- **Why it Exists**: Guarantees cancellation of broker SL before software trailing takes ownership.
- **Where Enforced**: `PositionStateReconstructor.validate_state_invariants()`.
- **Consequences of Violation**: Duplicate exit execution.

---

### **Invariant 5: Trailing SL Value Presence**
- **Description**: If `position_state` is `SOFTWARE_TRAILING_ACTIVE` or `PARTIALLY_PROTECTED`, `active_trailing_sl` MUST NOT be `None` and MUST be `> 0`.
- **Why it Exists**: Prevents software exit engine from evaluating against an undefined or zero SL price threshold.
- **Where Enforced**: `PositionStateReconstructor.validate_state_invariants()`.
- **Consequences of Violation**: Unprotected trade running without any stop-loss.

---

### **Invariant 6: Single In-Flight Exit Order**
- **Description**: Maximum of ONE in-flight software exit order (`order_role="EXIT_ALL"`) can exist per trade.
- **Why it Exists**: Prevents duplicate exit submissions on rapid sequential ticks.
- **Where Enforced**: `OrderManagerService._execute_workflow_plan()`.
- **Consequences of Violation**: Multiple market orders placed for same trade, creating accidental short positions.

---

### **Invariant 7: Quantity Conservation**
- **Description**: `remaining_quantity` + sum of filled target exit quantities MUST equal `entry_filled_qty`.
- **Why it Exists**: Ensures complete position tracking across partial target fills.
- **Where Enforced**: `OrderRepository`, `OrderManagerService`.
- **Consequences of Violation**: Under-exiting or over-exiting trade on software exit trigger.

---

### **Invariant 8: Terminal CLOSED State Permanence**
- **Description**: Once a trade status becomes `CLOSED`, no tick processing, order placements, or state mutations may occur.
- **Why it Exists**: Prevents processing ticks for liquidated trades.
- **Where Enforced**: `OrderManagerRegistry`, `TickRouter`.
- **Consequences of Violation**: Unnecessary database queries and CPU overhead on historical trades.

---

### **Invariant 9: Recovery Broker-First Principle**
- **Description**: `StartupRecoveryService` MUST query broker REST order history before transitioning any transient state (`SL_CANCEL_PENDING`, `EXIT_PENDING`, `TARGET_ORDER_PENDING`).
- **Why it Exists**: Prevents acting on stale local DB assumptions when broker state changed during offline window.
- **Where Enforced**: `StartupRecoveryService._reconcile_in_flight_trade_state()`.
- **Consequences of Violation**: Missing offline fills or attempting to cancel already-filled orders.

---

### **Invariant 10: Dict-Safe Broker Confirmation Extraction**
- **Description**: All broker order placement responses MUST be extracted safely regardless of whether returned as Python dict or object attribute.
- **Why it Exists**: Prevents `AttributeError` runtime crashes when broker adapters return dict confirmations.
- **Where Enforced**: `OrderManagerService._execute_workflow_plan()`.
- **Consequences of Violation**: Runtime crash during order placement resulting in unrecorded orders.
