# 5. Database Documentation

## 5.1 Overview
The database schema tracks trade execution state, order history, position parameters, and trailing stop metrics. The `trades` and `orders` tables maintain strict ownership rules to guarantee consistency across execution services.

---

## 5.2 `trades` Table Key Fields Data Dictionary

| Column Name | Type | Nullable | Default | Description | Ownership & Update Rules |
|-------------|------|----------|---------|-------------|--------------------------|
| `id` | `INTEGER` | No | PK | Unique Trade ID | System generated |
| `execution_target_id` | `INTEGER` | No | FK | Reference to `execution_targets.id` | Set on trade creation |
| `status` | `VARCHAR(32)` | No | `"OPEN"` | High-level trade lifecycle status (`OPEN`, `PARTIALLY_CLOSED`, `CLOSED`, `SOFTWARE_SL_HIT`, `EXIT_ORDER_REJECTED`) | Updated by `OrderManagerService` & `StartupRecoveryService` |
| `position_state` | `VARCHAR(32)` | No | `"BROKER_PROTECTED"` | Specific position state machine state (`BROKER_PROTECTED`, `SL_CANCEL_PENDING`, `SOFTWARE_TRAILING_ACTIVE`, `PARTIALLY_PROTECTED`, `TARGET_ORDER_PENDING`, `EXIT_PENDING`, `CLOSED`) | Owned by `OrderManagerService` & `StartupRecoveryService` |
| `sl_intended` | `NUMERIC(12,4)`| Yes | `None` | Initial intended stop-loss price level | Set on trade creation |
| `t1_intended` | `NUMERIC(12,4)`| Yes | `None` | Intended Target 1 price level | Set on trade creation |
| `t2_intended` | `NUMERIC(12,4)`| Yes | `None` | Intended Target 2 price level | Set on trade creation |
| `active_trailing_sl`| `NUMERIC(12,4)`| Yes | `None` | Current dynamic software trailing stop price | **Owned exclusively by software trailing engine**. NULL during `BROKER_PROTECTED`, set on handover, ratchets upwards. |
| `trailing_sl_activated`| `BOOLEAN`| No | `False` | Flag indicating if handover to software trailing occurred | Set to `True` upon `SL_CANCEL_PENDING` / `SOFTWARE_TRAILING_ACTIVE` transition. |
| `entry_filled_qty` | `INTEGER` | Yes | `0` | Total entry filled quantity | Set when entry order completes |
| `remaining_quantity`| `INTEGER` | Yes | `None` | Remaining open position quantity | Updated on partial target exit fills. Equals `entry_filled_qty` prior to TP1 fill. |

---

## 5.3 `orders` Table Key Fields Data Dictionary

| Column Name | Type | Nullable | Default | Description | Ownership & Update Rules |
|-------------|------|----------|---------|-------------|--------------------------|
| `id` | `INTEGER` | No | PK | Internal order ID | System generated |
| `parent_order_id` | `INTEGER` | Yes | FK | Self-reference to parent `orders.id` | Set on child order creation |
| `idempotency_key` | `VARCHAR(64)`| No | Unique | UUID string preventing duplicate broker submissions | Created by Order Builder |
| `broker_order_id` | `VARCHAR(64)`| Yes | Index | External broker order identifier string | Written when broker adapter returns placement confirmation |
| `order_role` | `VARCHAR(32)` | No | - | Purpose (`ENTRY`, `STOPLOSS`, `TARGET_1`, `TARGET_2`, `EXIT_ALL`) | Set on order creation |
| `status` | `VARCHAR(32)` | No | `"PENDING"` | Order execution state (`PENDING`, `SUBMITTED`, `OPEN`, `PLACED`, `COMPLETE`, `CANCELLED`, `REJECTED`) | Updated by broker callbacks & recovery reconciliation |
| `quantity` | `INTEGER` | No | - | Order quantity | Set on creation |
| `filled_quantity` | `INTEGER` | No | `0` | Cumulative filled quantity | Updated on order execution webhooks/callbacks |

---

## 5.4 Schema Invariants & State Constraints

1. **Active Trailing SL Constraint**: `active_trailing_sl` MUST NOT be `NULL` when `position_state` is `SOFTWARE_TRAILING_ACTIVE` or `PARTIALLY_PROTECTED`.
2. **Broker SL Exclusivity Constraint**: When `position_state` is `SOFTWARE_TRAILING_ACTIVE`, no order record with `order_role="STOPLOSS"` may have `status` in `("OPEN", "SUBMITTED", "PLACED")`.
3. **Quantity Conservation**: `remaining_quantity` + sum of filled target quantities MUST equal `entry_filled_qty`.
