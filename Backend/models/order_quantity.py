# order_quantity.py - OrderQuantity Passive DTO
'use strict'

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class OrderQuantity:
    """
    Passive immutable DTO carrying the computed executable order quantity.
    
    Implements Section 5.8 (Quantity Calculator) of the Architecture Reference v1.3.
    
    Fields:
      - quantity (int): Final integer quantity (rounded down via floor and lot size)
      - effective_risk_rupees (Decimal): Effective monetary risk incurred by this quantity
    """
    quantity: int
    effective_risk_rupees: Decimal
