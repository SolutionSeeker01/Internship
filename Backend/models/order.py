from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship
from database.db import Base

class Order(Base):
    __tablename__ = "orders"

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_orders_idempotency_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    execution_target_id = Column(Integer, ForeignKey("signal_execution_targets.id", ondelete="SET NULL"), nullable=True, index=True)
    parent_order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=True, index=True)
    
    order_role = Column(String(20), nullable=False)
    broker_order_id = Column(String(50), nullable=True, index=True)
    idempotency_key = Column(String(64), nullable=False)
    symbol = Column(String(50), nullable=False, index=True)
    exchange = Column(String(10), nullable=False)
    action = Column(String(10), nullable=False)
    order_type = Column(String(20), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(12, 4), nullable=True)
    trigger_price = Column(Numeric(12, 4), nullable=True)
    status = Column(String(20), nullable=False, default="PLACED", index=True)
    filled_quantity = Column(Integer, nullable=True, default=0)
    average_price = Column(Numeric(12, 4), nullable=True)
    broker = Column(String(20), nullable=False, index=True)
    
    placed_at = Column(DateTime(timezone=True), nullable=True)
    filled_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    parent_order = relationship("Order", remote_side=[id], backref="child_orders")
    execution_target = relationship("ExecutionTarget", back_populates="orders")

