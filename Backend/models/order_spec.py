# order_spec.py - OrderSpec Passive DTO
'use strict'

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class OrderSpec:
    """
    Broker-agnostic specification for a single order submission attempt.
    
    Implements Section 5.9 (Order Builder) of the Architecture Reference v1.3.
    
    Fields:
      - symbol (str): Trading symbol (e.g. RELIANCE, INFY)
      - exchange (str): Target exchange (NSE, BSE, NFO, BFO, CDS)
      - action (str): Transaction type (BUY, SELL)
      - quantity (int): Validated integer quantity
      - order_type (str): MARKET, LIMIT, SL, SL_MARKET
      - product (str): Product classification (INTRADAY / MIS, DELIVERY / CNC)
      - validity (str): Order validity (DAY, IOC, TTL)
      - price (Optional[Decimal]): Limit price if applicable
      - trigger_price (Optional[Decimal]): Trigger price if applicable
      - idempotency_key (str): SHA256 idempotency key generated for this execution
      - estimated_value (Decimal): Estimated monetary order value (quantity * price)
    """
    symbol: str
    exchange: str
    action: str
    quantity: int
    order_type: str
    product: str
    validity: str
    price: Optional[Decimal]
    trigger_price: Optional[Decimal]
    idempotency_key: str
    estimated_value: Decimal

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "action": self.action,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "product": self.product,
            "validity": self.validity,
            "price": float(self.price) if self.price is not None else None,
            "trigger_price": float(self.trigger_price) if self.trigger_price is not None else None,
            "idempotency_key": self.idempotency_key,
            "estimated_value": float(self.estimated_value)
        }
