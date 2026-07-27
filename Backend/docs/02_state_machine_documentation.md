# 2. State Machine Documentation

## 2.1 Overview
The Position State Machine governs the exact status and stop-loss protection mode of an open trade. States progress deterministically from entry fill to final closure.

---

## 2.2 Exhaustive State Definitions

### **1. `BROKER_PROTECTED`**
- **Purpose**: Initial state post-entry fill. Position is protected by an active hard Stop-Loss order placed directly on the broker's exchange.
- **Owner**: Broker Exchange.
- **Allowed Transitions**:
  - `SL_CANCEL_PENDING` (when LTP reaches 70% of TP1 distance).
  - `CLOSED` (if broker SL order fills directly on exchange due to immediate adverse move).
- **Forbidden Transitions**:
  - `SOFTWARE_TRAILING_ACTIVE` (cannot jump directly without cancelling broker SL).
  - `EXIT_PENDING` (cannot trigger software exit while hard broker SL is active).
- **Recovery Behaviour**: On startup, query broker for SL order status. If OPEN/SUBMITTED, remain `BROKER_PROTECTED`. If FILLED, transition trade to `CLOSED`.
- **Invariants**: Must have an active child order with `order_role="STOPLOSS"` and `status` in `("OPEN", "SUBMITTED", "PLACED")`. `active_trailing_sl` MUST be `None`.

---

### **2. `SL_CANCEL_PENDING`**
- **Purpose**: Transient state while an asynchronous cancellation request for the broker SL order is in-flight.
- **Owner**: Software Order Manager (waiting for Broker confirmation).
- **Allowed Transitions**:
  - `SOFTWARE_TRAILING_ACTIVE` (when broker confirms SL cancellation).
  - `CLOSED` (if broker SL order filled right before cancel request processed).
- **Forbidden Transitions**:
  - `BROKER_PROTECTED` (cannot revert back to hard broker SL).
  - `TARGET_ORDER_PENDING` (cannot process targets while cancellation pending).
- **Recovery Behaviour**: Query broker for SL order status by `broker_order_id`.
  - If `CANCELLED` or `REJECTED`: transition to `SOFTWARE_TRAILING_ACTIVE`, set `active_trailing_sl`.
  - If `FILLED`: transition trade to `CLOSED`.
  - If still `OPEN`: resend cancel request or maintain `SL_CANCEL_PENDING`.
- **Invariants**: Hard broker SL ID recorded in state. `active_trailing_sl` set to baseline intended SL or initial calculated trailing SL.

---

### **3. `SOFTWARE_TRAILING_ACTIVE`**
- **Purpose**: Main software-managed position state. No hard broker SL exists on exchange. Software calculates dynamic trailing SL per tick and ratchets `active_trailing_sl` upwards.
- **Owner**: Application Software (`TrailingStopEngine`).
- **Allowed Transitions**:
  - `TARGET_ORDER_PENDING` (when Target 1 or Target 2 limit price hit).
  - `EXIT_PENDING` (when LTP breaches `active_trailing_sl`).
  - `PARTIALLY_PROTECTED` (after Target 1 fill).
- **Forbidden Transitions**:
  - `BROKER_PROTECTED` (re-placing broker hard SL is forbidden).
  - `SL_CANCEL_PENDING` (cancellation already complete).
- **Recovery Behaviour**: Reconstruct `active_trailing_sl` from highest observed price or DB record. Re-register in `OrderManagerRegistry` for tick routing.
- **Invariants**: Must have **NO active broker SL order** (`broker_order_id` is `None`). `active_trailing_sl` MUST be populated (`> 0`). `trailing_sl_activated` MUST be `True`.

---

### **4. `PARTIALLY_PROTECTED`**
- **Purpose**: State after Target 1 (TP1) has filled and partial quantity has been realized. Remaining quantity is managed by software trailing SL.
- **Owner**: Application Software.
- **Allowed Transitions**:
  - `TARGET_ORDER_PENDING` (when Target 2 limit price hit).
  - `EXIT_PENDING` (when LTP breaches software trailing SL for remaining quantity).
  - `CLOSED` (when final target or remaining exit fills).
- **Forbidden Transitions**:
  - `BROKER_PROTECTED` / `SL_CANCEL_PENDING`.
- **Recovery Behaviour**: Verify TP1 order fill status via broker API. Update `remaining_quantity` and resume software trailing for remaining volume.
- **Invariants**: `executed_targets` contains `"TARGET_1"`. `remaining_quantity < entry_filled_qty`. `active_trailing_sl > 0`.

---

### **5. `TARGET_ORDER_PENDING`**
- **Purpose**: Transient state while a partial target limit exit order (`TARGET_1` / `TARGET_2`) is in-flight at the broker.
- **Owner**: Broker / Software Coordinator.
- **Allowed Transitions**:
  - `SOFTWARE_TRAILING_ACTIVE` / `PARTIALLY_PROTECTED` (upon target fill or cancel confirmation).
  - `CLOSED` (if final target filled completely).
- **Forbidden Transitions**:
  - `EXIT_PENDING` (cannot fire full market exit while target limit order execution pending).
- **Recovery Behaviour**: Query broker for target order status by `broker_order_id`.
  - If `FILLED`: credit filled qty, update trade status to `PARTIALLY_CLOSED`, transition to `SOFTWARE_TRAILING_ACTIVE` / `PARTIALLY_PROTECTED`.
  - If `CANCELLED`: revert state to `SOFTWARE_TRAILING_ACTIVE`.
- **Invariants**: Active child order exists with `order_role` in `("TARGET_1", "TARGET_2")`.

---

### **6. `EXIT_PENDING`**
- **Purpose**: Transient state when software trailing SL has been breached and market exit order (`EXIT_ALL`) has been dispatched to broker.
- **Owner**: Broker Execution Adapter.
- **Allowed Transitions**:
  - `CLOSED` (upon market exit fill confirmation).
  - `SOFTWARE_TRAILING_ACTIVE` (if exit order was REJECTED by broker, allowing software retry).
- **Forbidden Transitions**:
  - `BROKER_PROTECTED`, `SL_CANCEL_PENDING`, `TARGET_ORDER_PENDING`.
- **Recovery Behaviour**: Query broker for exit order status by `broker_order_id`.
  - If `FILLED`: update trade `status="CLOSED"`, `position_state="CLOSED"`.
  - If `REJECTED` or not found: revert `position_state="SOFTWARE_TRAILING_ACTIVE"` to allow re-triggering market exit on next tick.
- **Invariants**: Exit market order dispatched with quantity equal to `remaining_quantity`.

---

### **7. `CLOSED`**
- **Purpose**: Terminal state. Position completely liquidated (via targets, software SL, or hard broker SL).
- **Owner**: None (Archived).
- **Allowed Transitions**: None (Terminal).
- **Forbidden Transitions**: All transitions.
- **Recovery Behaviour**: Ignored by `StartupRecoveryService`. Unregistered from `OrderManagerRegistry`. Skips all incoming tick processing.
- **Invariants**: `remaining_quantity == 0`. `closed_at` timestamp populated in DB. `status == "CLOSED"`.
