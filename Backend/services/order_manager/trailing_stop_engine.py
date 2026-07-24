# Backend/services/order_manager/trailing_stop_engine.py
"""
Trailing Stop-Loss Engine - Pure Calculation & Throttling Evaluation Module

Implements Section 5.15 Subsection 5 of ARCHITECTURE_REFERENCE.md (v1.5.3).
Provides deterministic calculation of activation thresholds, trailing stop prices,
and throttling evaluation against broker modification limits.
"""

from decimal import Decimal
from typing import Optional, Tuple
from utils.logger import get_logger

logger = get_logger(__name__)

# Default Throttling Configuration Thresholds (Section 5.15 Subsection 5c)
DEFAULT_TRAILING_SL_MIN_STEP_PCT = Decimal("0.0025")  # 0.25% minimum step improvement


def calculate_activation_level(
    entry_action: str,
    entry_price: Decimal,
    t1_price: Decimal
) -> Decimal:
    """
    Calculates the 70% Trailing Stop activation threshold per Section 5.15 Subsection 5a:
      BUY:  Activation Level = Entry + 0.70 * (T1 - Entry)
      SELL: Activation Level = Entry - 0.70 * (Entry - T1)

    Args:
        entry_action (str): BUY or SELL.
        entry_price (Decimal): Intended or filled entry price.
        t1_price (Decimal): Target 1 price.

    Returns:
        Decimal: Activation threshold price.
    """
    entry_price = Decimal(str(entry_price))
    t1_price = Decimal(str(t1_price))
    action = entry_action.upper().strip()

    if action == "BUY":
        return entry_price + (Decimal("0.70") * (t1_price - entry_price))
    elif action == "SELL":
        return entry_price - (Decimal("0.70") * (entry_price - t1_price))
    else:
        raise ValueError(f"Invalid entry_action: {entry_action}. Must be BUY or SELL.")


def is_trailing_stop_activated(
    entry_action: str,
    entry_price: Decimal,
    t1_price: Decimal,
    current_ltp: Decimal,
    already_activated: bool = False
) -> bool:
    """
    Evaluates whether Trailing Stop mode is active.

    Strict Architectural Contract (Section 5.15 Subsection 5a):
      - Trailing stop activation is a one-way state transition.
      - If already_activated is True, returns True immediately (one-way latch).
      - Otherwise, activates if LTP reaches or crosses the 70% threshold.

    Args:
        entry_action (str): BUY or SELL.
        entry_price (Decimal): Intended/filled entry price.
        t1_price (Decimal): Target 1 price.
        current_ltp (Decimal): Live Last Traded Price.
        already_activated (bool): Persistent state from trades.trailing_sl_activated.

    Returns:
        bool: True if trailing stop mode is active, False otherwise.
    """
    if already_activated:
        return True

    activation_level = calculate_activation_level(entry_action, entry_price, t1_price)
    current_ltp = Decimal(str(current_ltp))
    action = entry_action.upper().strip()

    if action == "BUY":
        return current_ltp >= activation_level
    elif action == "SELL":
        return current_ltp <= activation_level
    return False


def calculate_trailing_stop_price(
    entry_action: str,
    original_sl: Decimal,
    entry_price: Decimal,
    t1_price: Decimal,
    current_ltp: Decimal
) -> Decimal:
    """
    Calculates theoretical trailing stop price strictly per Section 5.15 Subsection 5b:
      BUY:  New SL = Original SL + (0.50 * (T1 - Entry)) + (0.25 * (LTP - Entry))
      SELL: New SL = Original SL - (0.50 * (Entry - T1)) - (0.25 * (Entry - LTP))

    MANDATORY RULE:
      Every calculation uses original_sl as its constant base.
      Never uses current/modified SL as the base (New SL = Original SL + Adjustment).

    Args:
        entry_action (str): BUY or SELL.
        original_sl (Decimal): Original signal stoploss price (constant).
        entry_price (Decimal): Entry price.
        t1_price (Decimal): Target 1 price.
        current_ltp (Decimal): Live Last Traded Price.

    Returns:
        Decimal: Theoretical trailing stop loss price.
    """
    original_sl = Decimal(str(original_sl))
    entry_price = Decimal(str(entry_price))
    t1_price = Decimal(str(t1_price))
    current_ltp = Decimal(str(current_ltp))
    action = entry_action.upper().strip()

    if action == "BUY":
        t1_component = Decimal("0.50") * (t1_price - entry_price)
        ltp_component = Decimal("0.25") * (current_ltp - entry_price)
        return original_sl + t1_component + ltp_component
    elif action == "SELL":
        t1_component = Decimal("0.50") * (entry_price - t1_price)
        ltp_component = Decimal("0.25") * (entry_price - current_ltp)
        return original_sl - t1_component - ltp_component
    else:
        raise ValueError(f"Invalid entry_action: {entry_action}. Must be BUY or SELL.")


def should_emit_sl_modification(
    entry_action: str,
    active_sl_price: Decimal,
    new_calculated_sl: Decimal,
    min_step_pct: Decimal = DEFAULT_TRAILING_SL_MIN_STEP_PCT
) -> bool:
    """
    Evaluates throttling policy per Section 5.15 Subsection 5c (Broker Rate-Limit Compliance):
      - Throttling controls ONLY when an updated SL is dispatched to the broker.
      - Emits modification request ONLY IF the newly calculated SL improves over active SL
        by at least min_step_pct.

    BUY Improvement:  new_calculated_sl >= active_sl_price * (1 + min_step_pct)
    SELL Improvement: new_calculated_sl <= active_sl_price * (1 - min_step_pct)

    Args:
        entry_action (str): BUY or SELL.
        active_sl_price (Decimal): Currently active broker SL order price.
        new_calculated_sl (Decimal): Theoretical newly calculated SL.
        min_step_pct (Decimal): Minimum percentage improvement threshold (default 0.25%).

    Returns:
        bool: True if modification request should be dispatched to broker, False if throttled.
    """
    active_sl_price = Decimal(str(active_sl_price))
    new_calculated_sl = Decimal(str(new_calculated_sl))
    min_step_pct = Decimal(str(min_step_pct))
    action = entry_action.upper().strip()

    if action == "BUY":
        min_required_sl = active_sl_price * (Decimal("1") + min_step_pct)
        return new_calculated_sl >= min_required_sl
    elif action == "SELL":
        max_required_sl = active_sl_price * (Decimal("1") - min_step_pct)
        return new_calculated_sl <= max_required_sl
    return False


def is_trailing_exit_triggered(
    entry_action: str,
    active_sl_price: Decimal,
    current_ltp: Decimal
) -> bool:
    """
    Evaluates trailing exit condition per Section 5.15 Subsection 5d:
      BUY:  LTP < active_sl_price (Price breached SL downwards)
      SELL: LTP > active_sl_price (Price breached SL upwards)

    Args:
        entry_action (str): BUY or SELL.
        active_sl_price (Decimal): Active trailing SL price.
        current_ltp (Decimal): Live Last Traded Price.

    Returns:
        bool: True if position must be exited, False otherwise.
    """
    active_sl_price = Decimal(str(active_sl_price))
    current_ltp = Decimal(str(current_ltp))
    action = entry_action.upper().strip()

    if action == "BUY":
        return current_ltp < active_sl_price
    elif action == "SELL":
        return current_ltp > active_sl_price
    return False
