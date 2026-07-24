from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from database.db import Base

class ExecutionTarget(Base):
    __tablename__ = "signal_execution_targets"

    __table_args__ = (
        UniqueConstraint("signal_id", "client_id", name="uq_signal_client_target"),
    )

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, ForeignKey("signals.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    status = Column(String(20), nullable=False, default="READY", index=True)
    skip_reason = Column(String(50), nullable=True)
    
    broker_order_id = Column(String(50), nullable=True, index=True)
    
    # Trade Engine additions required by Section 11 of the Architecture Reference
    idempotency_key = Column(String(64), nullable=True, index=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    fail_reason = Column(Text, nullable=True)
    fail_category = Column(String(20), nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    client = relationship("User", backref="execution_targets")
    orders = relationship("Order", back_populates="execution_target")
