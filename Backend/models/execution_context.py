# execution_context.py - ExecutionContext DTO and Sub-Structures
'use strict'

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional


@dataclass(frozen=True)
class FundsData:
    """
    Available account funds snapshot.
    Section 5.5 ExecutionContext contract.
    """
    available_cash: Decimal
    used_margin: Decimal
    net_value: Decimal


@dataclass(frozen=True)
class MarginsData:
    """
    Available account margins snapshot.
    Section 5.5 ExecutionContext contract.
    """
    available_margin: Decimal
    used_margin: Decimal
    collateral: Decimal


@dataclass(frozen=True)
class InstrumentInfo:
    """
    Instrument market structure metadata snapshot.
    Section 5.5 ExecutionContext contract.
    """
    lot_size: int
    tick_size: Decimal
    freeze_qty: int
    segment: str
    exchange: str


@dataclass(frozen=True)
class ExecutionContext:
    """
    Complete immutable execution context.
    
    Implements Section 5.5 (ExecutionContext Builder) of the Architecture Reference.
    Pure passive DTO per Principle P5.
    """
    session_valid: bool
    market_open: bool
    exchange_status: str
    funds: FundsData
    margins: MarginsData
    instrument_info: InstrumentInfo
    fetched_at: datetime
    broker: str
    signal: Optional[Dict[str, Any]] = None
    target: Optional[Dict[str, Any]] = None
    capabilities: Optional[Any] = None

    @property
    def execution_target_id(self) -> int:
        target = self.target or {}
        return int(target.get("id", 0))

    @property
    def signal_id(self) -> int:
        target = self.target or {}
        signal = self.signal or {}
        return int(target.get("signal_id", 0) or signal.get("id", 0))

    @property
    def client_id(self) -> int:
        target = self.target or {}
        return int(target.get("client_id", 0))
