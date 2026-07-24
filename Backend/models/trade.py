# Backend/models/trade.py

from datetime import datetime

from decimal import Decimal
from typing import Optional
from sqlalchemy import Column, Integer, String, Numeric, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from database.db import Base


class Trade(Base):
    """
    Trade ORM model representing an active or completed position lifecycle.
    
    Implements Section 11 (Database Schema Contracts - trades table) of ARCHITECTURE_REFERENCE.md.
    """
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    execution_target_id = Column(
        Integer,
        ForeignKey("signal_execution_targets.id"),
        unique=True,
        nullable=False,
        index=True
    )

    # Intended setup prices from Strategy Engine / Signal
    entry_intended_price = Column(Numeric(12, 4), nullable=False)
    sl_intended = Column(Numeric(12, 4), nullable=False)
    t1_intended = Column(Numeric(12, 4), nullable=True)
    t2_intended = Column(Numeric(12, 4), nullable=True)
    t3_intended = Column(Numeric(12, 4), nullable=True)

    # Filled entry details
    entry_filled_price = Column(Numeric(12, 4), nullable=True)
    entry_filled_qty = Column(Integer, nullable=True)

    # Position exit accounting
    exit_average_price = Column(Numeric(12, 4), nullable=True)
    exit_qty = Column(Integer, nullable=True)
    pnl_realized = Column(Numeric(12, 4), nullable=True, default=Decimal("0.0000"))
    pnl_unrealized = Column(Numeric(12, 4), nullable=True, default=Decimal("0.0000"))

    # Position Status: OPEN | PARTIALLY_CLOSED | CLOSED
    status = Column(String(20), nullable=False, default="OPEN", index=True)

    # Trailing Stop One-Way Latch Flag (Section 5.15 v1.5.3)
    trailing_sl_activated = Column(Boolean, nullable=False, default=False)

    # Timestamps
    opened_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
