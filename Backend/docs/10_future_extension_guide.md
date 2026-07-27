# 10. Future Extension Guide

## 10.1 Overview
This guide provides explicit architectural principles and extension patterns for adding new broker adapters (e.g. Upstox, Angel One), custom exit algorithms, additional profit target levels, or advanced execution workflows.

---

## 10.2 Architectural Rules (Non-Negotiable)

When extending the trading engine, developers **MUST NOT VIOLATE** the following core architectural rules:

1. **Never Re-introduce Broker Trailing SL Modification**: Do not invoke `broker.modify_order()` to move stop-loss levels on exchange servers. Trailing stops MUST remain software-managed once activated.
2. **Never Skip Startup Broker Reconciliation**: Any new position state or transient workflow state MUST include broker query logic in `StartupRecoveryService`.
3. **Always Use Dict-Safe Response Parsing**: Always extract broker order attributes using `isinstance(resp, dict)` checks.
4. **Enforce Invariant Validation**: Any modification to `PositionStateReconstructor` MUST pass all 10 architectural invariants.

---

## 10.3 Extension Blueprint: Adding a New Broker Adapter

To onboard a new broker (e.g. `UpstoxBrokerAdapter` or `AngelOneBrokerAdapter`):

### **Step 1: Inherit from `BaseBrokerAdapter`**
Create a new adapter class in `services/brokers/` extending `BaseBrokerAdapter`:

```python
from services.brokers.base import BaseBrokerAdapter, Dict, Any, Optional

class UpstoxBrokerAdapter(BaseBrokerAdapter):
    def place_order(self, order_spec: Any, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        # Implement API call
        # MUST return standard dict: {"broker_order_id": str(upstox_id), "status": "SUBMITTED"}
        pass

    def cancel_order(self, broker_order_id: str) -> Dict[str, Any]:
        # Implement cancellation
        # MUST return standard dict: {"broker_order_id": broker_order_id, "status": "CANCELLED"}
        pass

    def get_order_history(self, broker_order_id: str) -> Optional[Dict[str, Any]]:
        # Implement order lookup
        # MUST return standard dict containing "status" key
        pass
```

### **Step 2: Register in `BrokerFactory`**
Register the new broker adapter in `services/brokers/broker_factory.py`:

```python
class BrokerFactory:
    def get_broker(self, broker_name: str) -> BaseBrokerAdapter:
        broker_upper = broker_name.upper()
        if broker_upper == "ZERODHA":
            return ZerodhaBrokerAdapter(...)
        elif broker_upper == "UPSTOX":
            return UpstoxBrokerAdapter(...)
        elif broker_upper == "ANGELONE":
            return AngelOneBrokerAdapter(...)
        else:
            raise UnsupportedBrokerException(f"Broker {broker_name} is not supported.")
```

---

## 10.4 Extension Blueprint: Adding New Target Levels (e.g., TP3, TP4)

To support additional target profit levels:

1. **Database Schema**: Add `t3_intended`, `t3_percentage` columns to `trades` and `execution_targets` tables.
2. **Order Roles**: Define `ORDER_ROLE="TARGET_3"` in order schemas.
3. **Workflow Plan Generator**: Update `TargetExecutionWorkflowEngine` to append `PLACE_TARGET_LIMIT_TARGET_3` workflow steps upon partial fill of TP2.
4. **Position State Reconstructor**: Update `executed_targets` list handling in `reconstruct_position_state()` to track `"TARGET_3"` realization.

---

## 10.5 Extension Blueprint: Custom Exit Strategies (e.g. Indicator / ATR Trailing)

To introduce alternative trailing algorithms (e.g. ATR-based or Chandelier Exits):

1. Extend `TrailingStopEngine` with strategy selection parameters:
   ```python
   class TrailingStopEngine:
       def calculate_new_stop_loss(self, trade, current_high, strategy="PERCENTAGE"):
           if strategy == "PERCENTAGE":
               return self._calculate_percentage_sl(...)
           elif strategy == "ATR":
               return self._calculate_atr_sl(...)
   ```
2. Maintain invariant enforcement: `calculate_new_stop_loss()` MUST guarantee monotonic ratcheting (new SL >= active_trailing_sl) regardless of the underlying technical indicator calculation.
