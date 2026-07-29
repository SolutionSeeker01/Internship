# Backend/utils/tick_size.py
"""
Centralized Exchange Tick Size Normalization Utility

Normalizes prices to valid exchange tick size steps (e.g. 0.05 for NSE/BSE).
Preserves Decimal precision for financial calculation safety.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union


def normalize_tick_size(
    price: Optional[Union[Decimal, float, int, str]],
    tick_size: Union[Decimal, float, str] = Decimal("0.05")
) -> Optional[Decimal]:
    """
    Normalizes a price to the nearest valid exchange tick size step.
    
    Args:
        price: Price to normalize.
        tick_size: Exchange tick size step (default Decimal("0.05")).
        
    Returns:
        Optional[Decimal]: Normalized price rounded to nearest tick step, or None if price is None.
    """
    if price is None:
        return None

    try:
        p = Decimal(str(price))
        t = Decimal(str(tick_size))
        if t <= 0:
            return p

        # Round to nearest multiple of tick_size step
        steps = (p / t).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        normalized = steps * t
        return normalized.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal(str(price)) if price is not None else None
