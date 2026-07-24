# Backend/database/order_repository.py
"""
Order Repository - Database Persistence Layer for Order Entities

Implements functional database operations for reading, creating, updating,
and querying Order records in accordance with Section 11 of ARCHITECTURE_REFERENCE.md.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from database.db import SessionLocal
from models.order import Order
from utils.logger import get_logger

logger = get_logger(__name__)


def create_order(
    idempotency_key: str,
    symbol: str,
    exchange: str,
    action: str,
    order_type: str,
    quantity: int,
    broker: str,
    order_role: str = "ENTRY",
    execution_target_id: Optional[int] = None,
    parent_order_id: Optional[int] = None,
    broker_order_id: Optional[str] = None,
    price: Optional[Decimal] = None,
    trigger_price: Optional[Decimal] = None,
    status: str = "PLACED",
    filled_quantity: int = 0,
    average_price: Optional[Decimal] = None,
    placed_at: Optional[datetime] = None,
    session: Optional[Session] = None
) -> Order:
    """
    Persists a new Order entity record to the orders database table.
    
    Args:
        idempotency_key: Unique SHA256 idempotency key.
        symbol: Trading symbol identifier (e.g. RELIANCE).
        exchange: Target exchange (e.g. NSE, BSE, NFO).
        action: Transaction direction (BUY or SELL).
        order_type: Execution type (MARKET, LIMIT, SL, SL_MARKET).
        quantity: Order quantity.
        broker: Target broker platform identifier.
        order_role: Role of the order (ENTRY, STOPLOSS, TARGET_1, TARGET_2, TARGET_3).
        execution_target_id: Foreign key referencing execution_targets(id) (entry orders).
        parent_order_id: Foreign key referencing orders(id) for child leg orders.
        broker_order_id: Order identifier returned by broker.
        price: Order limit price.
        trigger_price: Order trigger price.
        status: Initial order status string (default "PLACED").
        filled_quantity: Initial executed quantity (default 0).
        average_price: Average fill price.
        placed_at: Timestamp when order was placed.
        session: Optional external SQLAlchemy Session.
        
    Returns:
        Order: The persisted Order ORM model instance.
    """
    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        order = Order(
            idempotency_key=idempotency_key,
            symbol=symbol,
            exchange=exchange,
            action=action,
            order_type=order_type,
            quantity=quantity,
            broker=broker,
            order_role=order_role,
            execution_target_id=execution_target_id,
            parent_order_id=parent_order_id,
            broker_order_id=broker_order_id,
            price=price,
            trigger_price=trigger_price,
            status=status,
            filled_quantity=filled_quantity,
            average_price=average_price,
            placed_at=placed_at or datetime.now()
        )
        db.add(order)
        if own_session:
            db.commit()
            db.refresh(order)
        else:
            db.flush()

        logger.info(f"Created order record id={order.id} role={order_role} status={status}")
        return order
    except SQLAlchemyError as e:
        if own_session:
            db.rollback()
        logger.error(f"Failed to create order record role={order_role}: {str(e)}")
        raise
    finally:
        if own_session:
            db.close()


def get_order_by_id(
    order_id: int,
    session: Optional[Session] = None
) -> Optional[Order]:
    """
    Retrieves a single Order entity record by primary key id.
    """
    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        return db.query(Order).filter(Order.id == order_id).first()
    finally:
        if own_session:
            db.close()


def get_order_by_broker_order_id(
    broker_order_id: str,
    session: Optional[Session] = None
) -> Optional[Order]:
    """
    Retrieves a single Order entity record by broker_order_id.
    """
    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        return db.query(Order).filter(Order.broker_order_id == broker_order_id).first()
    finally:
        if own_session:
            db.close()


def get_order_by_idempotency_key(
    idempotency_key: str,
    session: Optional[Session] = None
) -> Optional[Order]:
    """
    Retrieves a single Order entity record by unique idempotency_key.
    """
    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        return db.query(Order).filter(Order.idempotency_key == idempotency_key).first()
    finally:
        if own_session:
            db.close()


def get_entry_order_by_execution_target_id(
    execution_target_id: int,
    session: Optional[Session] = None
) -> Optional[Order]:
    """
    Retrieves the primary ENTRY Order entity record associated with an execution_target_id.
    """
    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        return db.query(Order).filter(
            Order.execution_target_id == execution_target_id,
            Order.order_role == "ENTRY"
        ).first()
    finally:
        if own_session:
            db.close()


def get_child_orders_by_parent_id(
    parent_order_id: int,
    session: Optional[Session] = None
) -> List[Order]:
    """
    Retrieves all child leg Order entity records (STOPLOSS, TARGET_1, etc.) referencing a parent entry order.
    """
    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        return db.query(Order).filter(Order.parent_order_id == parent_order_id).all()
    finally:
        if own_session:
            db.close()


def get_orders_by_status(
    statuses: List[str],
    session: Optional[Session] = None
) -> List[Order]:
    """
    Retrieves all Order entity records where status matches any value in the provided statuses list.
    """
    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        return db.query(Order).filter(Order.status.in_(statuses)).all()
    finally:
        if own_session:
            db.close()



def update_order(
    order_id: int,
    status: Optional[str] = None,
    broker_order_id: Optional[str] = None,
    filled_quantity: Optional[int] = None,
    average_price: Optional[Decimal] = None,
    price: Optional[Decimal] = None,
    trigger_price: Optional[Decimal] = None,
    quantity: Optional[int] = None,
    filled_at: Optional[datetime] = None,
    cancelled_at: Optional[datetime] = None,
    session: Optional[Session] = None
) -> Optional[Order]:
    """
    Updates column values on an existing Order entity record.
    
    Args:
        order_id: Primary key id of the target Order record.
        status: Optional updated status string.
        broker_order_id: Optional updated broker order id.
        filled_quantity: Optional updated executed quantity.
        average_price: Optional updated average execution price.
        price: Optional updated limit price.
        trigger_price: Optional updated trigger price.
        quantity: Optional updated total quantity.
        filled_at: Optional updated fill timestamp.
        cancelled_at: Optional updated cancellation timestamp.
        session: Optional external SQLAlchemy Session.
        
    Returns:
        Optional[Order]: The updated Order ORM model instance, or None if not found.
    """
    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            logger.warning(f"Order record id={order_id} not found for update.")
            return None

        if status is not None:
            order.status = status
        if broker_order_id is not None:
            order.broker_order_id = broker_order_id
        if filled_quantity is not None:
            order.filled_quantity = filled_quantity
        if average_price is not None:
            order.average_price = average_price
        if price is not None:
            order.price = price
        if trigger_price is not None:
            order.trigger_price = trigger_price
        if quantity is not None:
            order.quantity = quantity
        if filled_at is not None:
            order.filled_at = filled_at
        if cancelled_at is not None:
            order.cancelled_at = cancelled_at

        if own_session:
            db.commit()
            db.refresh(order)
        else:
            db.flush()

        logger.info(f"Updated order id={order.id} status={order.status}")
        return order
    except SQLAlchemyError as e:
        if own_session:
            db.rollback()
        logger.error(f"Failed to update order id={order_id}: {str(e)}")
        raise
    finally:
        if own_session:
            db.close()
