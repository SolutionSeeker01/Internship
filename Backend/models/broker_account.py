from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Date, func, UniqueConstraint
from sqlalchemy.orm import relationship
from database.db import Base

class BrokerAccount(Base):
    __tablename__ = "broker_accounts"

    __table_args__ = (
        UniqueConstraint('user_id', 'broker', name='uq_user_broker'),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    broker = Column(String(20), nullable=False, default="ZERODHA")
    account_name = Column(String(100), nullable=True)
    api_key = Column(Text, nullable=True)
    api_secret = Column(Text, nullable=True)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    last_login_trading_day = Column(Date, nullable=True)
    is_connected = Column(Boolean, default=False, nullable=False)
    broker_username = Column(String(100), nullable=True)
    broker_user_id = Column(String(50), unique=True, nullable=True)
    oauth_state = Column(String(255), nullable=True)
    oauth_state_created_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # One-to-Many relationship back-reference mapping
    user = relationship(
        "User",
        back_populates="broker_accounts"
    )
