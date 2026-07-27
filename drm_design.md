# Developer Validation Console (DVC) — Simplified Design

**Mission:** Validate the first live end-to-end trade through Zerodha.  
**Lifetime:** Temporary (retired once the production frontend is built).  
**Target:** 1 active trade at a time (e.g. 1-share / penny-stock live test).  
**Status:** Design only — no code yet.

---

## 1. Single Mission Goal

> "If I send one live signal to Zerodha, what information do I need to know whether the entire backend pipeline worked correctly?"

We are not building a platform, analytics tool, or operations dashboard.  
We are building a **lightweight single-screen cockpit** for one task:
1. Send signal via webhook.
2. Watch the engine process Stage 1 → Stage 7 live.
3. Observe SL placement, tick triggers, trailing updates, and target exits.
4. If something halts, instantly see **where it stopped** and **what it was waiting for**.

---

## 2. Technology Re-Evaluation: Rich vs Textual

### Recommendation: **Rich (`rich.live.Live`)**

| Feature | Rich Live | Textual |
|---|---|---|
| **Setup effort** | **1 single Python script** (~150 lines) | Requires widget classes, app structure, CSS layout |
| **Dependencies** | Already in `requirements.txt` | New dependency to install |
| **Complexity** | Extremely simple (re-renders a layout tree) | Medium (full TUI application framework) |
| **Sufficient for mission?** | **100% Yes** | Overkill for a temporary validation script |

**Decision:** Use **`rich.live.Live`**. It re-renders a clean, flicker-free terminal layout every 100ms. When the trade is complete, you hit `Ctrl+C` or let it exit cleanly. Zero leftover framework baggage.

---

## 3.1 Deterministic Trade Selection Hierarchy

To ensure 100% predictable console behavior when multiple trades exist or arrive concurrently, the console determines which trade to display using a strict 3-tier precedence hierarchy:

```
Tier 1: Explicit CLI Target Flag (--trade-id ID)
   └─► If specified, stick strictly to this Trade ID until exit.

Tier 2: Newest Active Trade (Auto-Latch Mode - Default)
   └─► Automatically latches onto the most recently created trade that is NOT CLOSED.

Tier 3: Idle / Waiting Mode
   └─► If all trades are CLOSED or no trade exists, display "WAITING FOR SIGNAL INGESTION".
```

### Multi-Trade Handling Rules

1. **Auto-Latch (Default)**: When a new signal arrives (e.g. `#42` while `#41` is active), the console displays a top notification `⚡ NEW TRADE DETECTED: #42 — Auto-switching focus to #42` and focuses on the newest active trade.
2. **Explicit CLI Lock**: Running `python dev_tools/validation_console.py --trade-id 41` forces the console to lock strictly onto `#41`, ignoring any later signals.
3. **Manual Cycle Key**: The trade header displays `ACTIVE TRADES: [ #41 | #42 ◄ | #43 ] (Press 'N' to cycle focus)`. Pressing `N` manually shifts focus between active trades.

---

## 3. Simplified Terminal Screen Layout

```
╔════════════════════════════════════════════════════════════════════════════════════╗
║ ENGINE: 🟢 ACTIVE    ZERODHA: 🟢 OK    TICK FEED: 🟢 OK    14:32:05 IST            ║  ← 1. HEALTH HEADER
╠════════════════════════════════════════════════════════════════════════════════════╣
║ CURRENT TRADE: #42  |  SYMBOL: IDEA  |  ACTION: BUY  |  QTY: 20                    ║  ← 2. TRADE HEADER
║ ENTRY: ₹15.00       |  CURRENT LTP: ₹15.35  (↑)                                    ║
╠════════════════════════════════════════════════════════════════════════════════════╣
║ ⏳ CURRENT WAITING STATE:  [ WAITING FOR TARGET 1 OR SL TRIGGER ]                   ║  ← 3. WAITING STATE
╠════════════════════════════════════════════════════════════════════════════════════╣
║ TRADE TIMELINE (PERSISTENT STAGES)                                                 ║  ← 4. PERSISTENT TIMELINE
║  ✅ Stage 1: Signal Validated          (14:31:00.120)                             ║
║  ✅ Stage 2: Execution Context Built   (14:31:00.340)                             ║
║  ✅ Stage 3: Risk Passed               (14:31:00.342)  MaxRisk=₹10.00             ║
║  ✅ Stage 4: Quantity Calculated       (14:31:00.343)  Qty=20                     ║
║  ✅ Stage 5: Order Spec Built          (14:31:00.344)                             ║
║  ✅ Stage 6: Entry Submitted           (14:31:00.510)  Order=KZ-9901              ║
║  ✅ Stage 7: Entry Filled              (14:31:02.100)  Price=₹15.00               ║
║  ✅ Stage 8: Initial SL Placed         (14:31:02.850)  Order=KZ-9902 @ ₹14.50     ║
║  🔄 Stage 9: Position Protected        (14:31:02.850)  Watching Ticks             ║
║  ⏳ Stage 10: Target 1 Execution       (pending)       Target=₹16.00              ║
║  ⏳ Stage 11: Trade Completion         (pending)                                  ║
╠════════════════════════════════════════════════════════════════════════════════════╣
║ ACTIVE BROKER ORDERS                                                               ║  ← 5. ORDERS TABLE
║  Role       Status   Qty  TriggerPrice  LimitPrice (5% Buf)  BrokerOrderID         ║
║  STOPLOSS   OPEN     20   ₹14.50        ₹13.775              KZ-9902               ║
╠════════════════════════════════════════════════════════════════════════════════════╣
║ RECENT EVENTS & LOGS                                                               ║  ← 6. RECENT LOG STREAM
║  14:32:04 [TICK]     LTP=₹15.35 — no trigger                                       ║
║  14:32:02 [TSL]      Activated! Threshold ₹15.70 hit — initial TSL=₹14.80          ║
║  14:31:02 [ORDER_MGR] Initial SL placed at broker: KZ-9902                         ║
╚════════════════════════════════════════════════════════════════════════════════════╝
```

---

## 4. The 6 Essential Display Sections

### Section 1: Health Header (Top Single Line)
- **Engine**: Active / Inactive
- **Zerodha**: Broker connection & token valid
- **Tick Feed**: WebSocket live / stale
- **Clock**: Current IST timestamp

### Section 2: Current Trade Header
- Trade ID, Symbol, Action (BUY/SELL), Quantity
- Intended Entry Price vs. Live Last Traded Price (LTP) with tick direction arrow `(↑/↓)`

### Section 3: Dedicated "Current Waiting State" Banner (CRITICAL)
Prominently answers: **"What is the engine currently waiting for?"**

Possible Waiting States:
| Waiting State Banner Text | What Engine Is Doing |
|---|---|
| `[ WAITING FOR SIGNAL INGESTION ]` | Idle, listening for webhook |
| `[ WAITING FOR ENTRY ORDER FILL ]` | Entry order sent to Zerodha; waiting for broker execution callback |
| `[ WAITING FOR INITIAL SL PLACEMENT ]` | Entry filled; placing safety Stop Loss at broker |
| `[ WAITING FOR TARGET 1 OR SL TRIGGER ]` | Position protected; streaming ticks to detect price piercing T1/SL |
| `[ WAITING FOR SL CANCELLATION CONFIRMATION ]` | Target hit; awaiting broker confirmation that old SL is cancelled |
| `[ WAITING FOR TARGET EXIT FILL ]` | SL cancelled; reactive LIMIT exit order submitted to Zerodha |
| `[ WAITING FOR REPLACEMENT SL PLACEMENT ]` | Partial target filled; placing new SL for remaining quantity |
| `[ TRADE COMPLETE — ALL TARGETS / SL FILLED ]` | Trade finished cleanly |
| `[ ❌ HALTED: EXCEPTION IN STAGE X ]` | Error occurred; execution paused |

### Section 4: Persistent Trade Timeline (NEVER SCROLLS OUT)
Unlike a scrolling log where old events disappear off-screen, this panel stays fixed. It lists every step in the pipeline from start to finish.

**Visual Indicators:**
- `✅` = Step successfully completed (with timestamp and key metric)
- `🔄` = Currently active step
- `⏳` = Pending future step
- `❌` = Failed / rejected step

If a trade stalls, you look directly at this panel to see the last `✅` and the current `🔄` / `❌`.

### Section 5: Active Broker Orders
Shows all active orders present at Zerodha for this trade:
- Role (`ENTRY`, `STOPLOSS`, `TARGET_1`, etc.)
- Status (`SUBMITTED`, `OPEN`, `COMPLETE`, `CANCELLED`)
- Quantity
- Trigger Price (actual trigger level)
- Limit Execution Price (includes the 5% buffer)
- Broker Order ID

### Section 6: Recent Events Log (Bottom 4–5 Lines)
A small rolling window of raw runtime events for immediate context (e.g. tick arrivals, trailing stop math updates, broker responses).

---

## 5. Halted / Exception Diagnostic View

If an exception occurs, the **Waiting State Banner** turns bold RED:

```
╠════════════════════════════════════════════════════════════════════════════════════╗
║ ❌ HALTED AT STAGE 6 (Entry Submission): Zerodha API Timeout                       ║
╠════════════════════════════════════════════════════════════════════════════════════╣
║ EXCEPTION DETAILS                                                                  ║
║  Error:      zerodha.exceptions.NetworkError: Connection timed out after 5000ms    ║
║  File:       services/brokers/zerodha.py:142 in place_order()                      ║
║  Last Step:  Stage 5: Order Spec Built (14:31:00.344)                              ║
║  Failed:     Stage 6: Entry Submitted                                              ║
║  Safety:     No orders active at broker. Account is safe.                          ║
╚════════════════════════════════════════════════════════════════════════════════════╝
```

---

## 6. Architecture: Passive Event Bus

The architecture remains clean and decoupled:

```
┌────────────────────────────────────────────────────────┐
│                   BACKEND ENGINE                       │
│  TradeEngine → OrderManagerService → Zerodha Interface │
└───────────────────────────┬────────────────────────────┘
                            │
                            │ emit(RuntimeEvent) [Non-blocking]
                            ▼
               ┌──────────────────────────┐
               │    RuntimeEventBus       │ (thread-safe Queue)
               └────────────┬─────────────┘
                            │
                            │ consume()
                            ▼
               ┌──────────────────────────┐
               │  Developer Validation    │ (Standalone Rich Script)
               │      Console (DVC)       │
               └──────────────────────────┘
```

- **Zero risk to backend**: The monitor runs in a separate daemon thread or standalone script listening to `RuntimeEventBus`.
- **Backend proceeds if monitor fails**: If Rich crashes or terminal is closed, live trading continues uninterrupted.
- **Easy removal**: Delete `dev_tools/validation_console.py` when done — zero backend imports to cleanup.

---

## 7. Structured Logging Standards

Every log line generated across backend services during a trade will follow this strict key-value standard:

```
[TIMESTAMP] [LEVEL] [COMPONENT] [Trade:ID] [Order:BROKER_ID] MESSAGE key=value
```

**Key Examples for E2E Validation:**

1. **Signal Received**:
   `14:31:00.120 INFO TRADE_ENGINE [Trade:42] [Order:-] SIGNAL_RECEIVED symbol=IDEA action=BUY entry=15.00 sl=14.50 t1=16.00`

2. **Risk & Quantity**:
   `14:31:00.343 INFO QTY_CALC [Trade:42] [Order:-] QTY_CALCULATED qty=20 max_risk=10.00 rps=0.50 margin_req=300.00`

3. **Entry Submitted**:
   `14:31:00.510 INFO BROKER_DISPATCH [Trade:42] [Order:KZ-9901] ENTRY_SUBMITTED action=BUY qty=20 limit_price=15.00`

4. **Entry Filled**:
   `14:31:02.100 INFO BROKER_CALLBACK [Trade:42] [Order:KZ-9901] ENTRY_FILLED status=COMPLETE filled_qty=20 avg_price=15.00`

5. **Initial SL Placed**:
   `14:31:02.850 INFO ORDER_MGR [Trade:42] [Order:KZ-9902] INITIAL_SL_PLACED role=STOPLOSS qty=20 trigger=14.50 limit=13.775`

6. **Target Triggered & Exit Executed**:
   `14:35:10.020 INFO ORDER_MGR [Trade:42] [Order:KZ-9903] TARGET_EXIT_PLACED trigger_event=TP1_HIT role=TARGET_1 qty=10 limit=15.20`

With this format, a single `grep "[Trade:42]"` reconstructs the entire lifecycle of a trade instantly.

---

## 8. Summary Comparison

| Aspect | Old Proposal | **New Simplified Proposal (DVC)** |
|---|---|---|
| **Goal** | Full operations dashboard | **Single-trade live validation tool** |
| **Technology** | Textual (TUI framework) | **Rich Live (`rich.live.Live`)** — 1 simple script |
| **Multi-Trade** | Complex list + navigation | **Single active trade focus** |
| **Event Log** | Fast scrolling log | **Persistent 11-Stage Timeline + Dedicated Waiting State Banner** |
| **Lifetime** | Permanent dev tool | **Temporary script — discard after frontend is built** |
