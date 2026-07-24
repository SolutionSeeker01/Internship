# Backend/database/trade_repository.py
"""
Trade Repository - Database Persistence Layer for Trade Entities

Implements functional database operations for reading, creating, and updating
Trade records in accordance with Section 11 of ARCHITECTURE_REFERENCE.md.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from database.db import SessionLocal
from models.trade import Trade
from utils.logger import get_logger

logger = get_logger(__name__)


def create_trade(
    execution_target_id: int,
    entry_intended_price: Decimal,
    sl_intended: Decimal,
    t1_intended: Optional[Decimal] = None,
    t2_intended: Optional[Decimal] = None,
    t3_intended: Optional[Decimal] = None,
    entry_filled_price: Optional[Decimal] = None,
    entry_filled_qty: Optional[int] = None,
    status: str = "OPEN",
    trailing_sl_activated: bool = False,
    opened_at: Optional[datetime] = None,
    session: Optional[Session] = None
) -> Trade:
    """
    Persists a new Trade entity record to the trades database table.
    
    Args:
        execution_target_id: Foreign key referencing signal_execution_targets(id).
        entry_intended_price: Intended entry price.
        sl_intended: Intended stop-loss price.
        t1_intended: Target 1 price.
        t2_intended: Target 2 price.
        t3_intended: Target 3 price.
        entry_filled_price: Filled entry execution price.
        entry_filled_qty: Filled entry execution quantity.
        status: Initial trade status string.
        opened_at: Timestamp when the trade record was opened.
        session: Optional external SQLAlchemy Session.
        
    Returns:
        Trade: The persisted Trade ORM model instance.
    """
    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        trade = Trade(
            execution_target_id=execution_target_id,
            entry_intended_price=entry_intended_price,
            sl_intended=sl_intended,
            t1_intended=t1_intended,
            t2_intended=t2_intended,
            t3_intended=t3_intended,
            entry_filled_price=entry_filled_price,
            entry_filled_qty=entry_filled_qty,
            status=status,
            trailing_sl_activated=trailing_sl_activated,
            opened_at=opened_at or datetime.now()
        )
        db.add(trade)
        if own_session:
            db.commit()
            db.refresh(trade)
        else:
            db.flush()
        
        logger.info(f"Created trade record id={trade.id} for execution_target_id={execution_target_id}")
        return trade
    except SQLAlchemyError as e:
        if own_session:
            db.rollback()
        logger.error(f"Failed to create trade for execution_target_id={execution_target_id}: {str(e)}")
        raise
    finally:
        if own_session:
            db.close()


def get_trade_by_id(
    trade_id: int,
    session: Optional[Session] = None
) -> Optional[Trade]:
    """
    Retrieves a single Trade entity record by primary key id.
    """
    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        return db.query(Trade).filter(Trade.id == trade_id).first()
    finally:
        if own_session:
            db.close()


def get_trade_by_execution_target_id(
    execution_target_id: int,
    session: Optional[Session] = None
) -> Optional[Trade]:
    """
    Retrieves a single Trade entity record by foreign key execution_target_id.
    """
    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        return db.query(Trade).filter(Trade.execution_target_id == execution_target_id).first()
    finally:
        if own_session:
            db.close()


def get_open_trades(
    session: Optional[Session] = None
) -> List[Trade]:
    """
    Retrieves all Trade entity records where status is in ('OPEN', 'PARTIALLY_CLOSED').
    """
    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        return db.query(Trade).filter(Trade.status.in_(["OPEN", "PARTIALLY_CLOSED"])).all()
    finally:
        if own_session:
            db.close()


def update_trade(
    trade_id: int,
    status: Optional[str] = None,
    exit_average_price: Optional[Decimal] = None,
    exit_qty: Optional[int] = None,
    pnl_realized: Optional[Decimal] = None,
    pnl_unrealized: Optional[Decimal] = None,
    trailing_sl_activated: Optional[bool] = None,
    closed_at: Optional[datetime] = None,
    session: Optional[Session] = None
) -> Optional[Trade]:
    """
    Updates column values on an existing Trade entity record.
    """
    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        trade = db.query(Trade).filter(Trade.id == trade_id).first()
        if not trade:
            logger.warning(f"Trade record id={trade_id} not found for update.")
            return None

        if status is not None:
            trade.status = status
        if exit_average_price is not None:
            trade.exit_average_price = exit_average_price
        if exit_qty is not None:
            trade.exit_qty = exit_qty
        if pnl_realized is not None:
            trade.pnl_realized = pnl_realized
        if pnl_unrealized is not None:
            trade.pnl_unrealized = pnl_unrealized
        if trailing_sl_activated is not None:
            trade.trailing_sl_activated = trailing_sl_activated
        if closed_at is not None:
            trade.closed_at = closed_at

        if own_session:
            db.commit()
            db.refresh(trade)
        else:
            db.flush()

        logger.info(f"Updated trade id={trade.id} status={trade.status}")
        return trade
    except SQLAlchemyError as e:
        if own_session:
            db.rollback()
        logger.error(f"Failed to update trade id={trade_id}: {str(e)}")
        raise
    finally:
        if own_session:
            db.close()

