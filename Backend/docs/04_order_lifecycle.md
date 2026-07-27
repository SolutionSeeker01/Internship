# 4. Order Lifecycle

## 4.1 Overview
The execution system manages three categories of orders: Entry Orders, Target Profit Orders, and Stop-Loss / Exit Orders. All child orders link hierarchically to the parent Entry Order.

---

## 4.2 Order Category Specifications

### **1. Entry Order (`ORDER_ROLE="ENTRY"`)**
- **Trigger**: Webhook signal ingest -> `SignalValidator` -> `ExecutionTarget`.
- **Action**: `BUY` (Long) or `SELL` (Short).
- **Type**: `LIMIT` or `MARKET`.
- **Status Progression**: `SUBMITTED` -> `PLACED` -> `COMPLETE`.
- **Parent**: None (Root order).

### **2. Protective Broker Stop-Loss Order (`ORDER_ROLE="STOPLOSS"`)**
- **Trigger**: Automatically submitted upon entry order fill during Phase 1 (`BROKER_PROTECTED`).
- **Action**: Opposite of Entry (`SELL` for Long).
- **Type**: `SL` (Stop-Loss Limit) or `SL-M` (Stop-Loss Market).
- **Trigger Price**: `sl_intended`.
- **Status Progression**: `SUBMITTED` -> `OPEN` -> `CANCEL_REQUESTED` -> `CANCELLED` (or `FILLED`).
- **Parent**: `parent_order_id = entry_order.id`.

### **3. Target Profit Orders (`ORDER_ROLE="TARGET_1"`, `ORDER_ROLE="TARGET_2"`)**
- **Trigger**: Reaching 70% handover or Target price evaluation.
- **Action**: Opposite of Entry.
- **Type**: `LIMIT`.
- **Price**: `t1_intended`, `t2_intended`.
- **Status Progression**: `SUBMITTED` -> `PLACED` -> `COMPLETE`.
- **Parent**: `parent_order_id = entry_order.id`.

### **4. Software Exit Market Order (`ORDER_ROLE="EXIT_ALL"`)**
- **Trigger**: Market tick breaching `active_trailing_sl` in software.
- **Action**: Opposite of Entry.
- **Type**: `MARKET`.
- **Quantity**: `remaining_quantity`.
- **Status Progression**: `SUBMITTED` -> `COMPLETE`.
- **Parent**: `parent_order_id = entry_order.id`.

---

## 4.3 Child Order Hierarchy & Relationships

```
                        ┌───────────────────────────────┐
                        │   Parent Entry Order          │
                        │   (id=100, role="ENTRY")       │
                        └───────────────┬───────────────┘
                                        │
         ┌──────────────────────────────┼──────────────────────────────┐
         ▼                              ▼                              ▼
┌──────────────────┐           ┌──────────────────┐           ┌──────────────────┐
│ Protective SL    │           │ Target 1 Order   │           │ Software Exit    │
│ (role="STOPLOSS",│           │ (role="TARGET_1",│           │ (role="EXIT_ALL",│
│  parent_id=100)  │           │  parent_id=100)  │           │  parent_id=100)  │
└──────────────────┘           └──────────────────┘           └──────────────────┘
```

---

## 4.4 Broker Order ID Mapping

Every order dispatched to an exchange adapter receives a unique `broker_order_id` string upon successful submission:

- **Local Identification**: Internal `orders` table uses integer Primary Key `id` and UUID string `idempotency_key`.
- **Broker Correlation**: The `broker_order_id` field maps internal order records 1:1 with broker order books.
- **Safe Dictionary Extraction**: Broker adapters return dictionary confirmations `{"broker_order_id": "...", "status": "..."}` which are safely parsed using dict getters:
  ```python
  broker_order_id = (
      confirmation.get("broker_order_id")
      if isinstance(confirmation, dict)
      else getattr(confirmation, "broker_order_id", None)
  )
  ```
