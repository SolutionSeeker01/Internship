# 1. Architecture Overview

## Executive Summary
The Software-Managed Trailing Stop-Loss System is a high-performance, fault-tolerant execution engine designed to manage trade position protection and trailing stop calculations entirely within application software, eliminating broker API rate-limiting, slippage penalties, and order modification rejections.

---

## 1.1 Trade Lifecycle

```
[ ENTRY SIGNAL ]
       │
       ▼
┌──────────────────────┐
│   BROKER_PROTECTED   │ ◄── Initial Entry filled; Hard Broker SL order active
└──────────┬───────────┘
           │ Price reaches 70% threshold toward Target 1 (TP1)
           ▼
┌──────────────────────┐
│  SL_CANCEL_PENDING   │ ◄── Cancel request dispatched to Broker for hard SL
└──────────┬───────────┘
           │ Broker confirms SL cancellation (or order history verifies CANCELLED)
           ▼
┌──────────────────────────┐
│ SOFTWARE_TRAILING_ACTIVE │ ◄── Trailing SL calculated in software per tick
└──────────┬───────────────┘
           │
 ┌─────────┴────────────────────────────┐
 │ Market Price breaches Trailing SL    │ Target 1 (TP1) Limit Price Hit
 ▼                                      ▼
┌──────────────────────┐      ┌──────────────────────┐
│     EXIT_PENDING     │      │ TARGET_ORDER_PENDING │ ◄── Partial exit order placed
└──────────┬───────────┘      └──────────┬───────────┘
           │ Exit Filled                 │ TP1 Filled (Remaining qty updated)
           ▼                             └───────┬──────────────┘
┌──────────────────────┐                         │
│        CLOSED        │ ◄───────────────────────┘ (All targets / exit complete)
└──────────────────────┘
```

---

## 1.2 Stop-Loss Ownership Model

The system enforces a **Single Ownership Model** for stop-loss management:

1. **Broker Ownership Phase (`BROKER_PROTECTED`)**:
   - Initial protective Stop-Loss order resides on the broker's exchange servers (`ORDER_ROLE="STOPLOSS"`).
   - Protects position against sudden flash crashes prior to trade progression.

2. **Handover Transition Phase (`SL_CANCEL_PENDING`)**:
   - As market price approaches 70% of Target 1 distance from entry, software dispatches an asynchronous cancellation call (`cancel_order()`) for the hard broker SL order.

3. **Software Ownership Phase (`SOFTWARE_TRAILING_ACTIVE` / `PARTIALLY_PROTECTED`)**:
   - Ownership transfers 100% to software. No broker SL order exists on exchange servers.
   - Incoming high-frequency ticks evaluate against `TrailingStopEngine`.
   - Ratcheting updates `active_trailing_sl` in memory and DB (persisted on changes).
   - If market price drops below `active_trailing_sl`, software generates a market exit order (`EXIT_ALL`).

---

## 1.3 Responsibilities Breakdown

### **Broker Responsibilities**
- Execute entry limit/market orders (`ENTRY`).
- Hold hard initial protective stop-loss orders (`STOPLOSS`) during Phase 1.
- Execute target profit limit orders (`TARGET_1`, `TARGET_2`).
- Execute emergency/software exit market orders (`EXIT_ALL`).
- Provide real-time order status updates via webhooks/callbacks and REST order history API.

### **Software Responsibilities**
- Evaluate 70% handover trigger on every incoming market tick.
- Manage order cancellation workflows during handover.
- Maintain and ratchet `active_trailing_sl` deterministically based on high prices.
- Trigger immediate market exits when trailing stop levels are breached.
- Reconstruct exact trade and position states upon service startup (`StartupRecoveryService`).
- Enforce structural state invariants and prevent duplicate order submissions.

---

## 1.4 Component Interaction Diagram

```
┌─────────────────┐       Tick        ┌──────────────────┐
│  Tick Router /  │──────────────────►│   OrderManager   │
│ Market Data Feed│                   │     Service      │
└─────────────────┘                   └────────┬─────────┘
                                               │
                       ┌───────────────────────┼───────────────────────┐
                       ▼                       ▼                       ▼
           ┌──────────────────────┐┌──────────────────────┐┌──────────────────────┐
           │ TrailingStopEngine   ││PositionState         ││ OrderManagerRegistry │
           │ (Ratchet Logic)      ││Reconstructor         ││ (In-Memory Mapping)  │
           └──────────────────────┘└──────────────────────┘└──────────────────────┘
                       │                       │                       │
                       └───────────────────────┼───────────────────────┘
                                               │
                                               ▼
                                   ┌──────────────────────┐
                                   │  Broker Factory /    │
                                   │   Broker Adapter     │
                                   └───────────┬──────────┘
                                               │
                                               ▼
                                    ┌────────────────────┐
                                    │ Broker REST API /  │
                                    │  Exchange Engine   │
                                    └────────────────────┘
```
