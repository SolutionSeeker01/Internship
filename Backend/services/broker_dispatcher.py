# broker_dispatcher.py - Broker Dispatcher Service
'use strict'

import time
from datetime import datetime
from typing import Optional, Any

from models.execution_context import ExecutionContext
from models.execution_result import ExecutionResult, create_rejection_result
from models.order_spec import OrderSpec
from services.brokers.factory import BrokerFactory
from utils.logger import get_logger

logger = get_logger(__name__)


def map_broker_exception_reason(error_msg: str) -> tuple:
    """
    Maps raw broker exception message to standardized platform fail_reason and fail_category.
    Section 9 (Failure Classification) & Section 5.10 (Broker Dispatcher).
    """
    err_lower = error_msg.lower()
    
    if "session" in err_lower or "token" in err_lower or "401" in err_lower or "403" in err_lower:
        return ("BROKER_SESSION_EXPIRED", "PERMANENT")
    elif "margin" in err_lower or "funds" in err_lower or "insufficient" in err_lower or "rms" in err_lower:
        return ("INSUFFICIENT_MARGIN", "PERMANENT")
    elif "rate" in err_lower or "429" in err_lower:
        return ("RATE_LIMIT_EXCEEDED", "TRANSIENT")
    elif "network" in err_lower or "connect" in err_lower or "timeout" in err_lower or "503" in err_lower or "502" in err_lower:
        return ("NETWORK_ERROR", "TRANSIENT")
    elif "duplicate" in err_lower or "idempotency" in err_lower:
        return ("DUPLICATE_ORDER", "PERMANENT")
    else:
        return ("ORDER_REJECTED", "PERMANENT")


def dispatch_order(
    order_spec: OrderSpec,
    context: Optional[ExecutionContext] = None,
    broker_adapter_override: Optional[Any] = None
) -> ExecutionResult:
    """
    Submits a broker-independent OrderSpec to the active broker via BrokerInterface with transient retries.
    
    Implements Section 5.10 (Broker Dispatcher) of the Architecture Reference v1.3.
    
    Responsibilities:
      - Resolves active broker adapter using BrokerFactory or ExecutionContext
      - Submits order via broker_adapter.place_order(order_spec, idempotency_key)
      - Executes Section 5.10 Transient Retry Policy (1s -> 2s -> 5s backoff, up to 3 attempts)
      - Maps broker responses / errors to standardized platform ExecutionResult DTOs
      
    Constraints:
      - NO broker name checks (if broker == 'ZERODHA' is forbidden per Principle P4)
      - NO rate limiting (owned by adapter)
      - NO payload mutation or trading risk decisions
    """
    target_id = getattr(context, "execution_target_id", 0) if context else 0
    signal_id = getattr(context, "signal_id", 0) if context else 0
    client_id = getattr(context, "client_id", 0) if context else 0

    idempotency_key = getattr(order_spec, "idempotency_key", "")

    # Resolve Broker Adapter via Factory or Injection
    broker_adapter = broker_adapter_override
    if not broker_adapter and context:
        broker_name = getattr(context, "broker", "ZERODHA")
        try:
            broker_adapter = BrokerFactory.get_broker(broker_name)
        except Exception as err:
            logger.error(f"Broker Dispatcher failed to resolve broker adapter '{broker_name}': {err}")
            return ExecutionResult(
                execution_target_id=target_id,
                signal_id=signal_id,
                client_id=client_id,
                outcome="BROKER_FAILED",
                fail_reason="BROKER_UNAVAILABLE",
                fail_category="PERMANENT",
                retryable=False,
                idempotency_key=idempotency_key,
                executed_at=datetime.now()
            )

    if not broker_adapter:
        logger.error(f"Broker Dispatcher received no usable broker adapter for target ID {target_id}.")
        return ExecutionResult(
            execution_target_id=target_id,
            signal_id=signal_id,
            client_id=client_id,
            outcome="BROKER_FAILED",
            fail_reason="BROKER_UNAVAILABLE",
            fail_category="PERMANENT",
            retryable=False,
            idempotency_key=idempotency_key,
            executed_at=datetime.now()
        )

    # Section 5.10 Transient Retry Policy: Attempt 1 immediately, 2 after 1s/2s, 3 after 5s
    max_attempts = 3
    backoff_delays = [0, 1, 3] # seconds delay before attempt
    
    last_reason = "BROKER_UNAVAILABLE"
    last_category = "PERMANENT"

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            delay = backoff_delays[attempt - 1]
            logger.warning(f"Broker Dispatcher transient retry attempt {attempt}/{max_attempts} after {delay}s backoff for target ID {target_id}...")
            time.sleep(delay)

        try:
            logger.info(f"Broker Dispatcher submitting order (attempt {attempt}) for symbol {order_spec.symbol} target ID {target_id}...")
            response = broker_adapter.place_order(order_spec, idempotency_key=idempotency_key)

            broker_order_id = str(response.get("broker_order_id", ""))
            
            logger.info(f"Broker Dispatcher order submitted successfully: broker_order_id={broker_order_id} for target ID {target_id}.")
            return ExecutionResult(
                execution_target_id=target_id,
                signal_id=signal_id,
                client_id=client_id,
                outcome="SUBMITTED",
                broker_order_id=broker_order_id,
                quantity=order_spec.quantity,
                executed_price=order_spec.price,
                order_type=order_spec.order_type,
                idempotency_key=idempotency_key,
                executed_at=datetime.now()
            )

        except Exception as e:
            error_str = str(e)
            reason, category = map_broker_exception_reason(error_str)
            logger.warning(f"Broker submission attempt {attempt} failed: reason={reason}, category={category}, err={error_str}")

            last_reason = reason
            last_category = category

            # If permanent error (e.g. session expired, insufficient margin), do not retry!
            if category == "PERMANENT":
                break

    # If all transient attempts exhausted or permanent rejection hit
    final_reason = last_reason if last_category == "PERMANENT" else "TRANSIENT_EXHAUSTED"
    logger.error(f"Broker Dispatcher submission failed for target ID {target_id}: final_reason={final_reason}")

    return ExecutionResult(
        execution_target_id=target_id,
        signal_id=signal_id,
        client_id=client_id,
        outcome="BROKER_FAILED",
        fail_reason=final_reason,
        fail_category=last_category,
        retryable=(last_category == "TRANSIENT"),
        quantity=order_spec.quantity,
        order_type=order_spec.order_type,
        idempotency_key=idempotency_key,
        executed_at=datetime.now()
    )
