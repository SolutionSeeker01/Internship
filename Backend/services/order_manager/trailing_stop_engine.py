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


def update_monotonic_trailing_sl(
    entry_action: str,
    active_trailing_sl: Optional[Decimal],
    new_calculated_sl: Decimal
) -> Decimal:
    """
    Enforces Invariant 8: Monotonic Trailing Stop Ratchet for Software Trailing Engine.
    
    BUY:  Max(active_trailing_sl, new_calculated_sl) -> Only increases (ratchets up).
    SELL: Min(active_trailing_sl, new_calculated_sl) -> Only decreases (ratchets down).

    Args:
        entry_action (str): BUY or SELL.
        active_trailing_sl (Optional[Decimal]): Currently active persisted trailing SL price.
        new_calculated_sl (Decimal): Candidate trailing SL price from current tick.

    Returns:
        Decimal: Monotonically ratcheted trailing SL price.
    """
    new_calculated_sl = Decimal(str(new_calculated_sl))
    if active_trailing_sl is None:
        return new_calculated_sl

    active_sl = Decimal(str(active_trailing_sl))
    action = entry_action.upper().strip()

    if action == "BUY":
        return max(active_sl, new_calculated_sl)
    elif action == "SELL":
        return min(active_sl, new_calculated_sl)
    else:
        raise ValueError(f"Invalid entry_action: {entry_action}. Must be BUY or SELL.")
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
        return current_ltp <= active_sl_price
    elif action == "SELL":
        return current_ltp >= active_sl_price
    return False

