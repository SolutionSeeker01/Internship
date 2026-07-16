# client_strategy_preference.py - Client Strategy Preference Database Model
'use strict'

from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import relationship
from database.db import Base

class ClientStrategyPreference(Base):
    __tablename__ = "client_strategy_preferences"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False, index=True)
    
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    lot_multiplier = Column(Numeric(10, 2), default=1.00, nullable=False)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="strategy_preferences")
    strategy = relationship("Strategy", back_populates="preferences")
