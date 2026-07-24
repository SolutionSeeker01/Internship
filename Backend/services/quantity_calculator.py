# quantity_calculator.py - Quantity Calculator Service
'use strict'

import math
from decimal import Decimal
from typing import Dict, Any, Union, Optional

from models.execution_context import ExecutionContext, InstrumentInfo
from models.execution_result import ExecutionResult, create_rejection_result
from models.order_quantity import OrderQuantity
from models.risk_budget import RiskBudget
from utils.logger import get_logger

logger = get_logger(__name__)


def calculate_order_quantity(
    risk_budget: RiskBudget,
    signal_data: Dict[str, Any],
    instrument_info: Optional[InstrumentInfo] = None,
    context: Optional[ExecutionContext] = None
) -> Union[OrderQuantity, ExecutionResult]:
    """
    Converts a RiskBudget, Signal, and InstrumentInfo into a concrete, integer order quantity.
    
    Implements Section 5.8 (Quantity Calculator) of the Architecture Reference v1.3.
    """
    action = str(signal_data.get("action", "")).upper().strip()
    
    # Extract entry and stoploss as Decimal
    try:
        entry = Decimal(str(signal_data.get("entry", 0)))
        stoploss = Decimal(str(signal_data.get("stoploss", 0) or signal_data.get("sl", 0)))
    except Exception as e:
        logger.warning(f"Quantity Calculator received invalid price format: {e}")
        return create_rejection_result(
            context,
            outcome="RISK_REJECTED",
            fail_reason="INVALID_SIGNAL_PRICES",
            fail_category="PERMANENT"
        )

    # Defensive Lot Size Safety check (Review Point 2)
    lot_size = 1
    if instrument_info and getattr(instrument_info, "lot_size", None) is not None:
        try:
            lot_size = max(1, int(instrument_info.lot_size))
        except (ValueError, TypeError):
            lot_size = 1

    # Calculate risk per share & validate signal price boundaries (Review Point 1: Standardized error code)
    if action == "BUY":
        risk_per_share = entry - stoploss
        if risk_per_share <= Decimal("0"):
            logger.warning(f"Quantity Calculator rejected BUY signal: entry ({entry}) <= stoploss ({stoploss})")
            return create_rejection_result(
                context,
                outcome="RISK_REJECTED",
                fail_reason="INVALID_SIGNAL_PRICES",
                fail_category="PERMANENT"
            )
    elif action == "SELL":
        risk_per_share = stoploss - entry
        if risk_per_share <= Decimal("0"):
            logger.warning(f"Quantity Calculator rejected SELL signal: stoploss ({stoploss}) <= entry ({entry})")
            return create_rejection_result(
                context,
                outcome="RISK_REJECTED",
                fail_reason="INVALID_SIGNAL_PRICES",
                fail_category="PERMANENT"
            )
    else:
        logger.warning(f"Quantity Calculator rejected unknown action: '{action}'")
        return create_rejection_result(
            context,
            outcome="RISK_REJECTED",
            fail_reason="INVALID_SIGNAL_ACTION",
            fail_category="PERMANENT"
        )

    # Raw floor quantity calculation
    raw_qty_dec = risk_budget.max_loss_rupees / risk_per_share
    raw_qty = math.floor(raw_qty_dec)

    # Lot size rounding down
    if lot_size > 1:
        quantity = (raw_qty // lot_size) * lot_size
    else:
        quantity = raw_qty

    # Check minimum quantity requirement
    if quantity < 1:
        logger.warning(f"Quantity Calculator rejected trade: calculated quantity ({quantity}) < 1")
        return create_rejection_result(
            context,
            outcome="RISK_REJECTED",
            fail_reason="QUANTITY_BELOW_MINIMUM",
            fail_category="PERMANENT"
        )

    # Calculate effective risk incurred by final integer quantity
    effective_risk = Decimal(str(quantity)) * risk_per_share

    return OrderQuantity(
        quantity=int(quantity),
        effective_risk_rupees=effective_risk
    )
