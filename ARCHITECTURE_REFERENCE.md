# Execution Pipeline Architecture Reference
**Status: FROZEN**
**Version: 1.5.3**
**Date: 2026-07-24**



This document is the authoritative architecture specification for the Trade Engine and its related execution pipeline. All future implementation work must conform to this document. Do not redesign frozen components without raising an explicit architectural conflict first.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture Principles](#2-architecture-principles)
3. [Domain Entity Model](#3-domain-entity-model)
4. [Complete Execution Flow](#4-complete-execution-flow)
5. [Component Specifications](#5-component-specifications)
   - 5.1 Signal Pipeline
   - 5.2 Eligibility Engine
   - 5.3 Execution Dispatcher
   - 5.4 Trade Engine
   - 5.5 ExecutionContext Builder
   - 5.6 Runtime Validator
   - 5.7 Risk Manager
   - 5.8 Quantity Calculator
   - 5.9 Order Builder
   - 5.10 Broker Dispatcher
   - 5.11 BrokerInterface & BrokerCapabilities
   - 5.12 ExecutionResult
   - 5.13 Execution Writer
   - 5.14 Crash Recovery Scanner
6. [State Machine](#6-state-machine)
7. [Idempotency Strategy](#7-idempotency-strategy)
8. [Transaction Boundaries](#8-transaction-boundaries)
9. [Failure Classification](#9-failure-classification)
10. [BrokerInterface Contract](#10-brokerinterface-contract)
11. [Database Schema Contracts](#11-database-schema-contracts)
12. [Testing Strategy & Simulation Model](#12-testing-strategy--simulation-model)
13. [Implementation Roadmap](#13-implementation-roadmap)
14. [Architectural Constraints](#14-architectural-constraints)

---

## 1. System Overview

```
TradingView Webhook
        │
        ▼
┌───────────────────────────────────────┐
│         SIGNAL PIPELINE               │
│  Authentication → Validation →        │
│  Target Calc → Duplicate Check →      │
│  Signal Persistence                   │
└───────────────┬───────────────────────┘
                │
                ▼
┌───────────────────────────────────────┐
│        ELIGIBILITY ENGINE             │
│  Strategy active? Client subscribed?  │
│  Broker configured? Connected? Token? │
│  → Creates READY / SKIPPED targets   │
│  → Posts notification to dispatcher  │
└───────────────┬───────────────────────┘
                │  HTTP 201 returned to TradingView
                ▼
        ════════════════════════
        BACKGROUND (decoupled)
        ════════════════════════
                │
                ▼
┌───────────────────────────────────────┐
│       EXECUTION DISPATCHER            │
│  Primary:  in-process notification    │
│  Fallback: DB poll (SKIP LOCKED, 2s) │
└───────────────┬───────────────────────┘
                │
                ▼
┌───────────────────────────────────────┐
│          TRADE ENGINE                 │
│  (thin coordinator — no business      │
│   logic lives here)                   │
│                                       │
│  1. ExecutionContext Builder          │
│  2. Runtime Validator                 │
│  3. Risk Manager                      │
│  4. Quantity Calculator               │
│  5. Order Builder                     │
│  6. Broker Dispatcher                 │
└───────────────┬───────────────────────┘
                │
                ▼
        ExecutionResult (passive DTO)
                │
                ▼
┌───────────────────────────────────────┐
│         EXECUTION WRITER              │
│  Updates execution_targets            │
│  Creates order row                    │
│  Emits structured log                 │
└───────────────┬───────────────────────┘

════════════════════════
RECOVERY
════════════════════════

Crash Recovery Scanner
  Runs at startup + every 60s
  Finds EXECUTING targets > 30s old
  Verifies with broker → reset or close
```

---

## 2. Architecture Principles

These principles are non-negotiable and apply to every component in this pipeline.

**P1 — Single Responsibility**
Every component has exactly one responsibility. If a component needs to be described with "and", it has too many.

**P2 — Thin Coordinator Pattern**
The Trade Engine contains zero business logic. It calls modules in sequence and propagates results. Business logic lives inside the modules.

**P3 — No Direct Database Writes from Domain Components**
The Trade Engine does not write to the database. The Execution Writer owns persistence. This keeps the Trade Engine testable without a database.

**P4 — Broker Agnosticism**
The Trade Engine, Order Builder, and Broker Dispatcher never reference Zerodha, Upstox, or any specific broker by name. They interact only with `BrokerInterface`.

**P5 — Passive ExecutionResult**
`ExecutionResult` is a passive DTO. It has no methods that perform side effects. It is immutable, serializable, and fully observable.

**P6 — No Transaction Held Across Network Calls**
A database transaction must never be open while a broker API call is in flight. The CLAIM transition commits before the broker call. The result is written after the broker call returns.

**P7 — Explicit State Ownership**
Every state in the execution lifecycle has exactly one owning component. No component writes to a state it does not own. State transitions use conditional UPDATEs to enforce this.

**P8 — Crash Recovery is Mandatory**
The system must recover from server crashes without placing duplicate orders or losing READY targets. Crash recovery is not a future concern — it is part of V1.

**P9 — Complete Decoupling & Simulation-First Validation**
The Trade Engine must be fully testable without placing real trades or risking capital. Real orders are an operational deployment choice, not an architectural testing requirement. All core modules must depend strictly on abstract contracts (`BrokerInterface`) and immutable data structures (`ExecutionContext`, `RiskBudget`, `OrderSpec`). If any module cannot be verified without a real broker execution, it violates this architecture.

**P10 — Strict Broker Session Isolation & Shared Observation Layer**
Broker sessions are private execution contexts. Platform state is the shared observation layer.
- **Broker Session Isolation:** Every broker session is an isolated execution context owned by exactly one authenticated account.
  - A MASTER broker session is used only for MASTER responsibilities (signal validation, market lookup, etc.).
  - A CLIENT broker session is used only for that CLIENT's trade execution and Order Manager.
  - No MASTER may access or consume a CLIENT's broker session.
  - No CLIENT may access or consume another CLIENT's broker session.
  - No broker connection or market data stream may be shared or reused across users.
- **Shared Observation Layer:** Cross-user visibility (MASTER monitoring dashboards, reporting) is achieved exclusively through platform-managed database records (`trades`, `orders`, `execution_targets`) and internal platform event streams (backend WebSockets), never through shared broker sessions or shared broker market data connections.



---

## 3. Domain Entity Model

### 3.1 Signal

| Attribute | Value |
|---|---|
| **Responsibility** | Immutable record of a trading instruction received from an external source |
| **Owner** | Signal Pipeline |
| **Created by** | Webhook Router |
| **Updated by** | Never — immutable after creation |
| **Lifetime** | Permanent (audit trail) |
| **Relationships** | Signal 1 → N ExecutionTargets |

**Key fields:** `strategy_id`, `symbol`, `action`, `entry`, `sl`, `t1`, `t2`, `t3`, `timeframe`, `signal_timestamp`, `status`, `validation_status`

---

### 3.2 ExecutionTarget

| Attribute | Value |
|---|---|
| **Responsibility** | Administrative eligibility record for one client for one signal |
| **Owner** | Eligibility Engine (creates), Trade Engine (claims and terminates) |
| **Created by** | Eligibility Engine |
| **Updated by** | Trade Engine only — sets EXECUTING, then SUBMITTED or terminal failure state |
| **Lifetime** | Permanent (audit trail) |
| **Relationships** | ExecutionTarget N → 1 Signal; ExecutionTarget 1 → 0..1 Order (entry); ExecutionTarget 1 → 0..1 Trade (future) |

**Key fields:** `signal_id`, `client_id`, `status`, `skip_reason`, `broker_order_id`, `fail_reason`, `fail_category`, `idempotency_key`, `claimed_at`, `executed_at`

---

### 3.3 Order

| Attribute | Value |
|---|---|
| **Responsibility** | Complete lifecycle record of a single broker order |
| **Owner** | Trade Engine (creates entry order row), Order Manager (creates SL/TP rows, updates all statuses) |
| **Created by** | Trade Engine on successful broker submission |
| **Updated by** | Order Manager on every fill, modification, or cancellation event |
| **Lifetime** | Permanent (audit trail) |
| **Relationships** | Order N → 1 ExecutionTarget (entry orders only); Order 1 → N Orders (self-referential: SL/TP are children of entry via `parent_order_id`) |

**Key fields:** `execution_target_id`, `parent_order_id`, `order_role` (ENTRY|STOPLOSS|TARGET_1|TARGET_2|TARGET_3), `broker_order_id`, `idempotency_key`, `symbol`, `exchange`, `action`, `order_type`, `quantity`, `price`, `trigger_price`, `status`, `filled_quantity`, `average_price`, `placed_at`, `filled_at`, `cancelled_at`, `broker`

> **Critical:** `exchange` must be stored on every order from day one. Symbols are not globally unique across exchanges.

---

## 4. Complete Execution Flow

```
Target has status = READY
         │
         ▼
Execution Dispatcher claims target (atomic)
  UPDATE execution_targets SET status='EXECUTING', claimed_at=NOW()
  WHERE id=:id AND status='READY'
  → 0 rows updated: another worker claimed it → abort
         │
         ▼
ExecutionContext Builder
  → verify broker session
  → fetch funds + margins (one combined call where possible; available_cash = Client Trading Capital)
  → fetch instrument info (lot_size, tick_size, freeze_qty, exchange)
  → check market open + exchange status
  → build ExecutionContext (passive DTO)
  → if any fetch fails: return ExecutionResult(RUNTIME_REJECTED)
         │
         ▼
Runtime Validator
  → market_open? exchange_status == NORMAL?
  → session_valid?
  → fetched_at not stale (< 15s)?
  → PASS: return None | FAIL: return ExecutionResult(RUNTIME_REJECTED, reason)
         │
         ▼
Risk Manager
  → available_cash > 0? (account solvency check)
  → calculate RiskBudget.max_loss_rupees = Client Trading Capital (available_cash) × 1% (0.01)
  → PASS: produce RiskBudget (passive DTO) | FAIL: return ExecutionResult(RISK_REJECTED, "INSUFFICIENT_FUNDS")
         │
         ▼
Quantity Calculator
  → RiskBudget + Signal (entry, sl) + InstrumentInfo → OrderQuantity (passive DTO)
  → BUY:  quantity = floor(RiskBudget.max_loss_rupees / (EntryPrice - StoplossPrice))
  → SELL: quantity = floor(RiskBudget.max_loss_rupees / (StoplossPrice - EntryPrice))
  → integer quantity always rounded down using floor
  → respect lot_size (round down to nearest lot for derivatives)
  → if quantity < 1: return ExecutionResult(RISK_REJECTED, "QUANTITY_BELOW_MINIMUM")
         │
         ▼
Order Builder
  → Signal + OrderQuantity + ExecutionContext + BrokerCapabilities → broker-agnostic OrderSpec (passive DTO)
  → check pre-flight order value / estimated margin <= available_margin (if failed: return ExecutionResult(RISK_REJECTED, "INSUFFICIENT_MARGIN"))
  → check BrokerCapabilities for required order features
  → attach idempotency_key
  → set order_type, price, trigger_price based on signal action
         │
         ▼
Broker Dispatcher
  → BrokerInterface.place_order(order_spec, idempotency_key)
  → adapter applies rate limiting before API call
  → broker accepts: return OrderConfirmation { broker_order_id }
  → broker rejects (permanent/RMS): return ExecutionResult(BROKER_FAILED or RISK_REJECTED)
  → broker timeout/5xx (transient): retry up to 3x with backoff
  → transient exhausted: return ExecutionResult(BROKER_FAILED, TRANSIENT_EXHAUSTED)
         │
         ▼
ExecutionResult (passive DTO, immutable)
         │
         ▼
Execution Writer
  → updates execution_targets status
  → creates order row (if SUBMITTED)
  → emits structured log entry (all outcomes)
         │
         ▼
Order Manager takes over (future)
  → monitors order status
  → places SL/TP on fill
  → manages cancellations
```

---

## 5. Component Specifications

### 5.1 Signal Pipeline
**Responsibility:** Receive, authenticate, validate, and persist trading signals.
**Status:** Built. Frozen.
**Inputs:** Webhook HTTP POST
**Outputs:** Signal row (VALIDATED/REJECTED), HTTP 201/400/401/422
**Must not:** Touch clients, subscriptions, or execution logic.

### 5.2 Eligibility Engine
**Responsibility:** Determine which clients are administratively and technically eligible to participate in signal execution, based solely on platform configuration and broker connection state.
**Status:** Built. Frozen.
**Inputs:** `signal_id`, `strategy_id`
**Outputs:** `ExecutionTarget` rows (READY or SKIPPED with reason), summary dict
**Must not:** Check funds, margin, market state, or any dynamic broker conditions.
**Must:** Post notification to Execution Dispatcher after creating READY targets.

### 5.3 Execution Dispatcher
**Responsibility:** Deliver READY execution targets to the Trade Engine with minimal latency and maximum reliability.
**Status:** Built. Frozen.
**Primary path:** In-process notification channel (asyncio.Queue or threading.Queue). Posted by Eligibility Engine immediately after target creation.
**Fallback path:** DB polling every 2 seconds using `FOR UPDATE SKIP LOCKED`. Handles crash recovery and missed notifications.
**Concurrency:** `FOR UPDATE SKIP LOCKED` ensures two workers never claim the same target.
**Must not:** Contain any execution logic. It only delivers targets.

### 5.4 Trade Engine
**Responsibility:** Translate a READY execution target into a submitted broker order with a confirmed order ID, and report the outcome.
**Status:** Built. Frozen skeleton.
**Inputs:** ExecutionTarget, Signal, BrokerAccount
**Outputs:** ExecutionResult (passive DTO)
**Contains:** Module calls only — no business logic.
**Must not:** Write to the database. Must not know broker names. Must not perform retries internally (retries are handled at the Broker Dispatcher level for transient broker failures only).

### 5.5 ExecutionContext Builder
**Responsibility:** Fetch all dynamic runtime state required for execution in one coordinated operation and package it into an `ExecutionContext`.
**Status:** Built. Frozen.

```
ExecutionContext {
    session_valid:      bool
    market_open:        bool
    exchange_status:    NORMAL | HALTED | PRE_OPEN | POST_CLOSE
    funds:              FundsData      { available_cash, used_margin, net_value }
    margins:            MarginsData    { available_margin, used_margin, collateral }
    instrument_info:    InstrumentInfo { lot_size, tick_size, freeze_qty, segment, exchange }
    fetched_at:         datetime
    broker:             str
    signal:             Dict[str, Any]
    target:             Dict[str, Any]
    capabilities:       BrokerCapabilities
}
```

**Trading Capital Definition:** `FundsData.available_cash` is the explicit trading capital snapshot value passed to downstream Risk Manager for risk budget calculations.
- **Phase 1 (Current):** Sourced from the connected Zerodha account via `get_funds()`.
- **Future Phases:** Sourced from whichever broker selected for the client's execution target.

**Staleness rule:** If `fetched_at > 15 seconds` old at time of use, reject and re-fetch.
**Must not:** Fetch LTP, quotes, holdings, or positions (lazy-load those at the point of need).

### 5.6 Runtime Validator
**Responsibility:** Verify that the execution context represents a valid runtime state for order placement.
**Status:** Built. Frozen.
**Inputs:** ExecutionContext
**Outputs:** `PASS` (None) or `ExecutionResult(outcome="RUNTIME_REJECTED", reason=...)`
**Checks (in order):**
1. `fetched_at` not stale (< 15s)
2. `session_valid == True`
3. `market_open == True`
4. `exchange_status == NORMAL`

**Must not:** Make broker API calls. All data comes from ExecutionContext.
**Must not:** Evaluate financial conditions (funds, margin) — that is Risk Manager's job.

---

### 5.7 Risk Manager
**Responsibility:** Evaluate client account solvency and determine the maximum allowable risk budget for this trade.
**Status:** Build V1.
**Inputs:** ExecutionContext, Signal (optional reference)
**Outputs:** `RiskBudget { max_loss_rupees, available_cash }` or `ExecutionResult(outcome="RISK_REJECTED", reason=...)`
**V1 checks & Risk Budget calculation:**
1. Verify `available_cash > 0` (Account solvency check)
2. Calculate allowable risk budget:
   ```
   RiskBudget.max_loss_rupees = Client Trading Capital (FundsData.available_cash) × 0.01
   ```

**Must not:** Calculate order quantity (that is Quantity Calculator's job).
**Must not:** Perform margin requirement checks requiring order quantity (owned by Order Builder & Broker RMS).
**Must not:** Make broker API calls or DB queries (uses ExecutionContext).

---

### 5.8 Quantity Calculator
**Responsibility:** Convert a `RiskBudget`, `Signal`, and `InstrumentInfo` into a concrete, integer order quantity.
**Status:** Build V1.
**Inputs:** RiskBudget, Signal (entry, sl, action), InstrumentInfo (lot_size, tick_size, freeze_qty)
**Outputs:** `OrderQuantity { quantity, effective_risk_rupees }` or `ExecutionResult(outcome="RISK_REJECTED", reason="QUANTITY_BELOW_MINIMUM")`
**V1 Position Sizing Formula:**
```
If Action == BUY:
    risk_per_share = EntryPrice - StoplossPrice
    quantity       = floor(RiskBudget.max_loss_rupees / risk_per_share)

If Action == SELL:
    risk_per_share = StoplossPrice - EntryPrice
    quantity       = floor(RiskBudget.max_loss_rupees / risk_per_share)
```
**Constraints:**
- Quantity must always be a non-negative integer.
- Division result is always rounded down using `floor`.
- If `quantity < 1`, return `ExecutionResult(outcome="RISK_REJECTED", fail_reason="QUANTITY_BELOW_MINIMUM")`.
- Performs no broker API calls, no account state checks, and no database operations. It is pure mathematical position sizing.


---

### 5.9 Order Builder
**Responsibility:** Translate signal parameters, order quantity, and execution context into a broker-agnostic `OrderSpec`.
**Status:** Build in V1.
**Inputs:** Signal, OrderQuantity, ExecutionContext, BrokerCapabilities
**Outputs:** `OrderSpec` (broker-agnostic) or `ExecutionResult(outcome="RISK_REJECTED", fail_reason="UNSUPPORTED_ORDER_TYPE")`
**Must:** Check BrokerCapabilities before building any order spec that requires a non-universal feature.
**Must:** Attach Layer 3 idempotency key (`SHA256(target_id:signal_id:client_id)`).
**Must:** Preserve explicit signal attributes (`order_type`, `price`, `trigger_price`, `action`, `symbol`).
**Must not:** Know broker names. Must not set broker-specific field values (product codes, variety strings). That translation belongs in the Broker Adapter.
**Must not:** Perform margin requirement checks or mutate explicit signal order types.



---

### 5.10 Broker Dispatcher
**Responsibility:** Submit an OrderSpec to the correct broker via BrokerInterface and return the raw outcome.
**Status:** Build in V1.
**Inputs:** OrderSpec, BrokerAccount
**Outputs:** OrderConfirmation { broker_order_id } or BrokerFailure { reason, category }
**Retry policy (transient failures only):**
- Attempt 1: Immediately
- Attempt 2: After 2 seconds
- Attempt 3: After 5 seconds
- Exhausted: return BrokerFailure(TRANSIENT_EXHAUSTED)

**Must not:** Know broker names. Uses `BrokerFactory.get_broker(account.broker)`.
**Must not:** Perform rate limiting. Rate limiting is the adapter's responsibility.

---

### 5.11 BrokerInterface & BrokerCapabilities
**Responsibility:** Define the stable contract that all broker adapters must implement.
**Status:** Build V1 subset. Full interface designed now.

**V1 required methods:**
```
verify_session()                    → SessionStatus
get_funds()                         → FundsData
get_margins(segment)                → MarginsData
estimate_margin(order_spec)         → MarginEstimate
get_instrument(symbol, exchange)    → InstrumentInfo
is_market_open(exchange)            → bool
place_order(spec, idempotency_key)  → OrderConfirmation
is_token_expired(issued_at)         → bool
get_login_url(state)                → str
handle_callback(params)             → CallbackData
```

**Future methods (design declared, implement with Order Manager):**
```
cancel_order(order_id)              → CancellationResult
modify_order(order_id, delta)       → OrderConfirmation
get_order(order_id)                 → OrderStatus
get_orders(date, status)            → List[OrderStatus]
get_positions()                     → List[Position]
get_holdings()                      → List[Holding]
get_ltp(symbol)                     → float
```

**BrokerCapabilities (declared on each adapter, V1):**
```
BrokerCapabilities {
    supports_order_modification:    bool
    supports_bracket_orders:        bool
    supports_trailing_sl:           bool
    supports_gtt:                   bool
    supports_amo:                   bool
    supports_sl_order:              bool
    supports_sl_market_order:       bool
    supported_product_types:        List[INTRADAY | DELIVERY]
    supported_order_types:          List[MARKET | LIMIT | SL | SL_MARKET]
    orders_per_second:              int
    api_calls_per_second:           int
}
```

**Rate limiting:** Implemented inside each Broker Adapter. In-process token bucket for V1. Redis-backed distributed token bucket when multi-worker deployment is needed.

---

### 5.12 ExecutionResult
**Responsibility:** Carry the complete outcome of a Trade Engine execution attempt as an immutable, serializable data object.
**Status:** Build in V1.

```
ExecutionResult {
    execution_target_id:    int
    signal_id:              int
    client_id:              int
    outcome:                SUBMITTED | RUNTIME_REJECTED | RISK_REJECTED |
                            BROKER_FAILED | INTERNAL_ERROR
    broker_order_id:        str | None
    fail_reason:            str | None
    fail_category:          TRANSIENT | PERMANENT | None
    retryable:              bool
    quantity:               int | None
    executed_price:         float | None
    order_type:             MARKET | LIMIT | None
    idempotency_key:        str
    executed_at:            datetime
}
```

**Must:** Be immutable. Have no methods with side effects. Be fully serializable.
**Must not:** Write to database. Must not emit events. Must not call any external service.

---

### 5.13 Execution Writer
**Responsibility:** Translate an ExecutionResult into database updates and a structured log entry.
**Status:** Build in V1.
**Inputs:** ExecutionResult
**Actions:**
1. Update `execution_targets` status to final state
2. If `SUBMITTED`: create `orders` row with `broker_order_id`
3. Emit structured log entry for every outcome

**Must not:** Contain business logic. It only translates ExecutionResult to persistence calls.

---

### 5.14 Crash Recovery Scanner
**Responsibility:** Detect and recover orphaned EXECUTING execution targets after server crashes or worker failures.
**Status:** Build in V1.
**Runs:** At server startup AND every 60 seconds as a background task.
**Query:**
```sql
SELECT * FROM execution_targets
WHERE status = 'EXECUTING'
AND claimed_at < NOW() - INTERVAL '30 seconds'
```

**Decision tree per orphaned target:**
```
broker_order_id IS NOT NULL:
    → query broker for order status
    → found: update DB to SUBMITTED, hand to Order Manager
    → not found: ALERT (should not happen) → mark FAILED

broker_order_id IS NULL:
    → query broker using idempotency_key
    → order found: update DB, hand to Order Manager
    → order not found: reset to READY (safe to retry)

broker unreachable during recovery:
    → leave as EXECUTING, retry in next cycle
```

---

### 5.15 Order Manager & Position Management Specification (v1.5)

**Responsibility:** Manage post-submission order lifecycles, live market tick monitoring, runtime target execution, limit-only exit orders, configurable trailing stop-loss throttling, and position PnL accounting.
**Status:** Build in V1.
**Inputs:** `orders` records (status `SUBMITTED`/`OPEN`), broker WebSocket order updates, LTP market data feeds.

#### 1. Execution Ownership & Master Monitoring Flow (Principle P10)
- **Client Execution Isolation:** Every Order Manager instance runs strictly within the private execution context of its target **CLIENT (`client_id`)**, consuming only that client's authenticated `BrokerInterface` session and client market data feed. MASTER sessions and other CLIENT sessions are strictly forbidden from accessing or executing commands through a third-party broker connection.
- **MASTER Monitoring Wording:** MASTER interfaces provide real-time operational visibility into all authorized client trades. This visibility is derived exclusively from platform-managed database state (`trades`, `orders`, `execution_targets`) and internal event streams published by the CLIENT's Order Manager (backend WebSockets). The MASTER never consumes the CLIENT's broker session, market data stream, `BrokerInterface`, or broker WebSocket directly, and cannot execute, modify, or cancel client orders.
- **Explicit Monitoring Pipeline Flow:**
  ```text
  CLIENT Broker Session
          ↓
  CLIENT BrokerInterface
          ↓
  CLIENT Order Manager
          ↓
  Persist Trade State / Publish Internal Platform Events
          ↓
  MASTER Dashboard (Read-Only Operational Visibility)
  ```
- **Monitored Position Attributes:** Through this platform observation layer, the MASTER Dashboard observes in real time: Entry status, Active position state, TP1 / TP2 / TP3 progress, Current Stop-Loss / Trailing Stop status, Remaining quantity ($Q_{\text{rem}}$), Realized & Unrealized P&L, and Position Closed status.
- **Initial Post-Entry Order Placement:** Immediately after a CLIENT's Entry Order fills (`filled_quantity` $Q$), the CLIENT's Order Manager places **ONLY ONE broker-side exit order**: a `STOPLOSS` limit order for the **entire filled position $Q$** at `stoploss_price` on the CLIENT's broker account.
- **Target Orders (TP1, TP2, TP3):** Target orders are **NOT** pre-placed at the broker. They are runtime targets monitored in memory by the CLIENT's Order Manager against tick LTP feeds.



#### 2. Position Target Quantity Split Policy
Target quantities are calculated at entry fill and stored in memory:
- **TP1 Quantity (50%):** $\lfloor Q \times 0.50 \rfloor$
- **TP2 Quantity (25%):** $\lfloor Q \times 0.25 \rfloor$ (Integer floor)
- **TP3 Quantity (25% / Remaining):** $Q - (\text{TP1 Qty} + \text{TP2 Qty})$

*Worked Examples:*
- **Q = 90:** TP1 = 45, TP2 = 22, TP3 = 23
- **Q = 100:** TP1 = 50, TP2 = 25, TP3 = 25

#### 3. Order Manager Position Lifecycle States
To track positions cleanly during temporary execution windows, the Order Manager maintains internal position lifecycle states:
- `PROTECTED`: Position is open and full Stop-Loss safety order is active at broker.
- `SL_CANCEL_PENDING`: Target level hit; cancellation request issued for active Stop-Loss order.
- `TARGET_ORDER_PENDING`: Stop-Loss cancellation confirmed; target `LIMIT` exit order placed at broker.
- `PARTIALLY_PROTECTED`: Partial target executed; new Stop-Loss safety order placed at broker for remaining quantity $Q_{\text{rem}}$.
- `CLOSED`: Position fully exited; realized PnL finalized.

#### 4. Runtime Target Execution Workflow (Sequential Cancel-Wait-Place-Protect)
When live market LTP reaches a target level (e.g. `t1` for TP1):
1. **Transition to `SL_CANCEL_PENDING`:** Order Manager issues `cancel_order` for the active Stop-Loss order.
2. **Await Cancellation Confirmation:** Waits for broker cancellation response.
3. **Transition to `TARGET_ORDER_PENDING`:** Submits `LIMIT` exit order for the target quantity (e.g. 45 for TP1).
4. **Transition to `PARTIALLY_PROTECTED`:** Upon target fill, places a new `STOPLOSS` limit order for the remaining open quantity ($Q_{\text{rem}} = Q - \text{Executed Target Qty}$).

*Operational Risk Note:* Acknowledges a brief unhedged execution window during transition states (`SL_CANCEL_PENDING` $\rightarrow$ `TARGET_ORDER_PENDING`).

#### 5. Trailing Stop Calculation Formulas & Throttling Strategy (Broker Rate-Limit Compliance)

**5a. Activation Threshold & One-Way Latch Contract**

Trailing stop logic activates when live LTP reaches **70% of the distance from Entry to T1**:
$$\text{Activation Level (BUY)} = \text{Entry} + 0.70 \times (\text{T1} - \text{Entry})$$
$$\text{Activation Level (SELL)} = \text{Entry} - 0.70 \times (\text{Entry} - \text{T1})$$

> **Architectural Contract — One-Way State Transition:** Trailing stop activation is a one-way state transition. Once the live market price reaches the activation threshold, trailing mode remains permanently enabled for the remainder of the trade, regardless of subsequent market retracements. This activation state must survive server restarts and crash recovery via the persistent `trades.trailing_sl_activated` boolean flag.


**5b. Trailing Stop Formulas (Authoritative)**

> **Definition — Original Stoploss Price:** The stop-loss price received with the original trading signal. It is **constant** for the entire lifetime of the trade. Every trailing stop calculation must always use this original stop-loss value as its base. The calculation must **never** use the previously modified trailing stop as the new base.
>
> ✅ **Correct:** `New SL = Original SL + Adjustment`
> ❌ **Incorrect:** `New SL = Current SL + Adjustment`

- **BUY Trailing Stop Formula:**
  $$\text{New Trailing SL} = \text{Original SL} + \Bigl(0.50 \times (\text{T1} - \text{Entry}) + 0.25 \times (\text{LTP} - \text{Entry})\Bigr)$$

- **SELL Trailing Stop Formula:**
  $$\text{New Trailing SL} = \text{Original SL} - \Bigl(0.50 \times (\text{Entry} - \text{T1}) + 0.25 \times (\text{Entry} - \text{LTP})\Bigr)$$

**5c. Throttling Policy (Broker Rate-Limit Compliance)**

The throttling policy controls **only when an updated Stop-Loss order is sent to the broker**. It never alters the trailing stop formula itself. The evaluation sequence is:

1. **Calculate** the theoretical trailing stop using the formulas in 5b above (always from Original SL base).
2. **Compare** the newly calculated value against the currently active broker Stop-Loss price.
3. **Emit a broker modification request only if** the improvement exceeds the configured minimum step threshold (`TRAILING_SL_MIN_STEP_PCT` or `TRAILING_SL_MIN_TICK_OFFSET`).

The business formula in 5b is always evaluated on every tick after activation. Throttling is a broker dispatch filter only — it does not change, skip, or approximate the mathematical result.

**5d. Trailing Exit Condition**

If LTP crosses the active Trailing SL, Order Manager cancels the active SL order and submits a `LIMIT` exit order for the entire remaining quantity $Q_{\text{rem}}$.



#### 6. Limit-Only Exit Policy & Broker Adapter Handoff (Principle P1 & P4)
- **Business Intent:** All exit orders (TP, Stop-Loss, Trailing Stop) are requested as `LIMIT` orders. Absolute market exit orders are strictly forbidden.
- **Broker Adapter:** Constructs the broker-specific API payload (setting trigger price and limit buffer thresholds).

#### 7. Explicit Trade Closure Rule
- **Rule:** If TP3 executes, or remaining open quantity reaches zero (via TP3, Stop-Loss, or Trailing Stop exit), the trade transitions to `CLOSED` status in the `trades` table, remaining orders are cancelled, and realized P&L is finalized.




---


## 6. State Machine

### States and Ownership

| State | Owner | Meaning |
|---|---|---|
| `READY` | Eligibility Engine | Eligible and waiting for execution |
| `EXECUTING` | Trade Engine | Atomically claimed by one worker |
| `RUNTIME_REJECTED` | Trade Engine | Market closed, token expired, etc. — terminal |
| `RISK_REJECTED` | Trade Engine | Insufficient funds/margin — terminal |
| `SUBMITTED` | Trade Engine → Order Manager | Broker accepted the order |
| `FAILED` | Trade Engine | Broker rejected or transient exhausted — terminal |
| `FILLED` | Order Manager | Entry order fully filled — terminal |
| `PARTIALLY_FILLED` | Order Manager | Entry partially filled, still open |
| `CANCELLED` | Order Manager | Order cancelled — terminal |
| `REJECTED_BY_EXCHANGE` | Order Manager | Exchange-level rejection post-submission — terminal |

### Allowed Transitions

```
READY               → EXECUTING             (Dispatcher atomic claim)
EXECUTING           → RUNTIME_REJECTED      (Runtime Validator fail)
EXECUTING           → RISK_REJECTED         (Risk Manager fail)
EXECUTING           → SUBMITTED             (Broker accepts order)
EXECUTING           → FAILED               (Broker permanent reject or transient exhausted)
EXECUTING           → READY                (Crash recovery ONLY, after broker verification)
SUBMITTED           → FILLED
SUBMITTED           → PARTIALLY_FILLED
SUBMITTED           → CANCELLED
SUBMITTED           → REJECTED_BY_EXCHANGE
PARTIALLY_FILLED    → FILLED
PARTIALLY_FILLED    → CANCELLED
```

### Illegal Transitions (enforced via conditional UPDATE)

```
READY               → SUBMITTED             ILLEGAL
READY               → FILLED               ILLEGAL
EXECUTING           → FILLED               ILLEGAL (must pass through SUBMITTED)
SUBMITTED           → EXECUTING            ILLEGAL
RUNTIME_REJECTED    → (any)                ILLEGAL (terminal)
RISK_REJECTED       → (any)                ILLEGAL (terminal)
FAILED              → (any)                ILLEGAL (terminal, no silent retry)
FILLED              → (any)                ILLEGAL (terminal)
CANCELLED           → (any)                ILLEGAL (terminal)
```

**Enforcement:** All state writes use conditional UPDATE:
```sql
UPDATE execution_targets
SET status = 'SUBMITTED', broker_order_id = :id
WHERE id = :target_id AND status = 'EXECUTING'
-- If 0 rows updated: illegal transition attempted → raise internal alert
```

---

## 7. Idempotency Strategy

Four layers. All four are mandatory.

**Layer 1 — Database Status Guard**
Before claiming, verify `status = 'READY'`. Abort if not.

**Layer 2 — Atomic CLAIM**
```sql
UPDATE execution_targets
SET status = 'EXECUTING', claimed_at = NOW()
WHERE id = :id AND status = 'READY'
```
If 0 rows updated → another worker claimed it → abort immediately.

**Layer 3 — Idempotency Key to Broker**
Generated before the broker call. Stored in `execution_targets.idempotency_key`.
```
idempotency_key = SHA256(f"{execution_target_id}:{signal_id}:{client_id}")
```
Sent with every broker order submission. Broker deduplicates on repeated submissions with the same key.

**Layer 4 — Pre-Retry Broker Order Check**
Before any retry attempt, check `execution_targets.broker_order_id`.
If already set → order was placed → do not re-submit. Update status from broker query instead.

---

## 8. Transaction Boundaries

**Rule: Never hold a database transaction open across a broker API call.**

```
Transaction 1: CLAIM (commit immediately)
    UPDATE execution_targets SET status='EXECUTING', claimed_at=NOW()
    WHERE id=:id AND status='READY'
    COMMIT

    ↕ No transaction open

    [Broker API call — may take 50ms to 5s]

    ↕ No transaction open

Transaction 2: RECORD RESULT (commit immediately)
    UPDATE execution_targets SET status=..., broker_order_id=...
    INSERT INTO orders (...)
    COMMIT
```

---

## 9. Failure Classification

| Failure | Category | Retry | Permanent | Notify Client | Log Level |
|---|---|---|---|---|---|
| Insufficient funds | Permanent | No | Yes | Yes | ERROR |
| Insufficient margin | Permanent | No | Yes | Yes | ERROR |
| Market closed | Temporal | Time-based | No | No | WARNING |
| Exchange halt | Temporal | When lifted | No | Yes | WARNING |
| RMS rejection | Permanent | No | Yes | Yes | ERROR |
| Token expired | Auth | No | Conditional | Yes | ERROR |
| Broker API timeout | Transient | Yes (3×) | No | No | WARNING |
| Broker 5xx | Transient | Yes (3×) | No | No | WARNING |
| Network interruption | Transient | Yes (3×) | No | No | WARNING |
| Freeze qty exceeded | Permanent | No | Yes | Yes | ERROR |
| Invalid order params | Permanent | No | Yes | Yes | ERROR |
| Duplicate order (idem key hit) | Idempotency | No | Yes | No | WARNING |
| Internal exception | Internal | No | Yes | Yes (alert) | CRITICAL |

**Transient retry policy:** 1s → 2s → 5s backoff. Three attempts maximum. After exhaustion, status = `FAILED`, fail_category = `TRANSIENT_EXHAUSTED`.

---

## 10. BrokerInterface Contract

See Section 5.11 for the complete method list.

**Key design rules:**
- Every method returns a broker-agnostic data class. No broker-specific types leave the adapter.
- Methods not supported by a broker raise `BrokerCapabilityNotSupported`.
- Methods are never removed from the interface. New methods are added with a default `raise NotImplementedError` on the base class.
- The adapter is the only file that knows about broker-specific field names, product codes, and API quirks.

---

## 11. Database Schema Contracts

### execution_targets (additions for Trade Engine)

```
idempotency_key     VARCHAR(64)     -- SHA256 key, set before broker call
claimed_at          TIMESTAMP       -- set on EXECUTING transition
fail_reason         TEXT            -- human-readable failure description
fail_category       VARCHAR(20)     -- TRANSIENT | PERMANENT | null
executed_at         TIMESTAMP       -- when Trade Engine completed
```

### orders (new table, V1)

```
id                  SERIAL PRIMARY KEY
execution_target_id INTEGER REFERENCES execution_targets(id)  -- entry orders only
parent_order_id     INTEGER REFERENCES orders(id)             -- SL/TP legs
order_role          VARCHAR(20)   -- ENTRY|STOPLOSS|TARGET_1|TARGET_2|TARGET_3
broker_order_id     VARCHAR(50)
idempotency_key     VARCHAR(64)
symbol              VARCHAR(50)
exchange            VARCHAR(10)   -- NSE|BSE|NFO|BFO|CDS  [required from day one]
action              VARCHAR(10)   -- BUY|SELL
order_type          VARCHAR(20)   -- MARKET|LIMIT|SL|SL_MARKET
quantity            INTEGER
price               DECIMAL(12,4)
trigger_price       DECIMAL(12,4)
status              VARCHAR(20)   -- PLACED|OPEN|COMPLETE|CANCELLED|REJECTED
filled_quantity     INTEGER
average_price       DECIMAL(12,4)
broker              VARCHAR(20)   -- ZERODHA|UPSTOX|ANGEL_ONE
placed_at           TIMESTAMP
filled_at           TIMESTAMP
cancelled_at        TIMESTAMP
created_at          TIMESTAMP DEFAULT NOW()
```

### trades (schema designed now, table created with Order Manager)

```
id                      SERIAL PRIMARY KEY
execution_target_id     INTEGER REFERENCES execution_targets(id) UNIQUE
entry_intended_price    DECIMAL(12,4)
sl_intended             DECIMAL(12,4)
t1_intended             DECIMAL(12,4)
t2_intended             DECIMAL(12,4)
t3_intended             DECIMAL(12,4)
entry_filled_price      DECIMAL(12,4)
entry_filled_qty        INTEGER
exit_average_price      DECIMAL(12,4)
exit_qty                INTEGER
pnl_realized            DECIMAL(12,4)
pnl_unrealized          DECIMAL(12,4)
status                  VARCHAR(20)   -- OPEN|PARTIALLY_CLOSED|CLOSED
opened_at               TIMESTAMP
closed_at               TIMESTAMP
created_at              TIMESTAMP DEFAULT NOW()
```

---

## 12. Testing Strategy & Simulation Model

Real orders are an operational deployment choice, not an architectural testing requirement. The Trade Engine architecture must be completely validated through in-memory simulation and test adapters without sending a single order to a real broker account or risking real capital.

```
Level 1: Pure Unit Tests (In-Memory Data Objects)
       │
       ▼
Level 2: Mock Broker Verification (MockBrokerAdapter)
       │
       ▼
Level 3: Paper Trading Simulation (PaperTradingAdapter + Live Ticks)  ← HIGHEST EXECUTION TEST
       │
       ▼
Level 4: Broker Integration Verification (Protocol & API Schema Checks)
```

### Level 1 — In-Memory Unit Testing
* **Scope:** Every module before the Broker Adapter (`RuntimeValidator`, `RiskManager`, `QuantityCalculator`, `OrderBuilder`, `ExecutionWriter`).
* **Execution:** Plain data objects in $\rightarrow$ deterministic results out. Executed entirely in memory.
* **Dependencies:** No broker, no DB, no HTTP, no WebSockets.
* **Example Test Flows:**
  ```
  ExecutionContext → RuntimeValidator → PASS / FAIL
  RiskBudget → QuantityCalculator → OrderQuantity
  Signal + OrderQuantity → OrderBuilder → OrderSpec
  ```

### Level 2 — Mock Broker Verification (`MockBrokerAdapter`)
* **Scope:** `BrokerDispatcher`, `TradeEngine` orchestration, retry mechanisms, failure mapping, state transitions.
* **Execution:** Implements `BrokerInterface`. Simulates error categories: `401/403 AuthExpired`, `429 RateLimited`, `503 BrokerTimeout`, `NetworkInterruption`, `RMSRejection`, and duplicate idempotency hits.
* **Dependencies:** Uses `MockBrokerAdapter` instead of `ZerodhaAdapter`.
* **Goal:** Validate orchestration, retry logic, `ExecutionResult` generation, and state machine transitions without real broker calls.

### Level 3 — Paper Trading Adapter (`PaperTradingAdapter`) — Primary Execution Validation
* **Scope:** Full End-to-End Execution Pipeline (`Signal` $\rightarrow$ `Eligibility Engine` $\rightarrow$ `Trade Engine` $\rightarrow$ `Order Manager` $\rightarrow$ `Database`).
* **Architecture:**
  ```
  BrokerInterface (Abstract Contract)
          ▲
          │
    ┌─────┴──────────────────┐
    │                        │
  ZerodhaAdapter      PaperTradingAdapter
  ```
* **Execution:** Implements `BrokerInterface`. Serves as the primary validation environment. Instead of sending orders to Zerodha, it:
  - Generates synthetic `broker_order_id` strings
  - Simulates accepted/rejected orders, fills, partial fills, and cancellations
  - Maintains a simulated order book, client positions, and real-time P&L
  - Matches orders against live market tick feeds (`KiteTicker` / WebSocket feed)
* **Goal:** Fully validate the Trade Engine and complete execution pipeline under real market conditions with zero capital risk.

### Level 4 — Broker Integration Verification (Protocol Only)
* **Scope:** Real broker adapter implementations (`ZerodhaAdapter`, `UpstoxAdapter`).
* **Execution:** Verifies broker authentication, OAuth login, session validation, instrument lookup, margin estimation, funds retrieval, API response parsing, and error mapping against the live broker API.
* **Goal:** Verify that the real broker adapter correctly communicates with the broker API. **Level 4 validates the Broker Adapter only—it does not validate the Trade Engine or business logic.**

---

## 13. Implementation Roadmap

### Prerequisites (before any Trade Engine code)

| Task | Reason |
|---|---|
| Drop `uq_single_active_master` index | CLIENT broker connections currently block MASTER connection |
| Create `orders` table | Trade Engine has nowhere to write its output without it |
| Add Trade Engine columns to `execution_targets` | `idempotency_key`, `claimed_at`, `fail_reason`, `fail_category`, `executed_at` |

### V1 — Build Now

| Component | Description |
|---|---|
| Execution Dispatcher | DB polling + in-process notification channel |
| ExecutionContext Builder | Session, funds, margins, instrument info |
| Runtime Validator | Market open, exchange status, session valid |
| Risk Manager V1 | Funds check, margin check, fixed quantity input |
| Quantity Calculator V1 | Equity cash segment only |
| Order Builder | Signal → broker-agnostic OrderSpec, BrokerCapabilities check |
| Broker Dispatcher | BrokerInterface call + transient retry |
| BrokerInterface V1 subset | place_order, get_funds, get_margins, verify_session, get_instrument |
| BrokerCapabilities | Declared on each adapter |
| ExecutionResult | Passive DTO |
| Execution Writer | Updates execution_targets, creates order row, structured log |
| Crash Recovery Scanner | Startup + 60s periodic scan |
| Idempotency | Atomic CLAIM + idempotency key to broker |
| State machine enforcement | Conditional UPDATEs on all transitions |
| Structured state transition logging | Every state change emits a log line |
| `MockBrokerAdapter` (Level 2 Test) | Simulates all broker failure categories in memory |
| `PaperTradingAdapter` (Level 3 Test) | Simulated order book using live market feed (Primary Pipeline Validation) |

### Design Now, Implement with Order Manager (V1)

| Component | Description |
|---|---|
| `trades` table | Schema above; create table when Order Manager is started |
| Order Manager V1 Core | Fill processing (`SUBMITTED` → `OPEN`), status polling |
| Quantity Split Policy | TP1 (50%), TP2 (25% INT), TP3 (Remaining Qty) |
| Limit-Only Exit Policy | TP, Stop-Loss, and Trailing Stop exit requests as LIMIT orders |
| Trailing Stop-Loss Engine | 70% activation threshold, BUY/SELL dynamic formulas |
| Partial Exit & OCO | Quantity recalculation on remaining $Q_{\text{rem}}$, SL adjustment |
| BrokerInterface | `cancel_order`, `get_order`, `modify_order` implementations |

### Future Enhancements

| Component | Trigger |
|---|---|
| Risk Manager V2 | When % risk, strategy limits, capital allocation needed |
| Quantity Calculator V2 | When futures/options added |
| Redis rate limiter | When multi-worker deployment needed |
| Distributed worker pool | When >100 simultaneous executions required |
| Position Manager V2 | When portfolio-level cross-strategy tracking needed |
| Broker WebSocket feed | When polling latency for fills is unacceptable |
| Portfolio risk tracking | When cross-client exposure limits required |
| GTT / bracket order support | When BrokerCapabilities declares support |


---

## 14. Architectural Constraints

These constraints must be respected in all future implementation work.

**C1:** The Trade Engine must never run synchronously inside the webhook HTTP request. Execution runs in a background worker after HTTP 201 is returned.

**C2:** The Trade Engine must not write to the database directly. All persistence goes through the Execution Writer.

**C3:** The Trade Engine must not reference any broker by name. All broker interaction goes through `BrokerInterface`.

**C4:** `ExecutionResult` must remain a passive DTO. No methods with side effects.

**C5:** No database transaction may be held open across a broker API call.

**C6:** The atomic CLAIM transition (`WHERE status='READY'`) is the concurrency boundary. Do not introduce any additional locking mechanism.

**C7:** Crash recovery must verify with the broker before resetting any orphaned target to READY.

**C8:** The `exchange` column must be present in the `orders` table from day one.

**C9:** Every state transition must use a conditional UPDATE. A zero-row result must trigger an internal alert.

**C10:** BrokerCapabilities must be declared on each adapter. Order Builder must consult capabilities before building any non-universal order spec.

**C11:** Every component must be testable without real broker credentials or real trades. Real orders are an operational deployment choice, not an architectural testing requirement.

**C12:** If an implementation detail conflicts with this document, stop and raise the conflict explicitly. Do not silently change the architecture.
