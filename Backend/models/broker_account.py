from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Date, func
from sqlalchemy.orm import relationship
from database.db import Base

class BrokerAccount(Base):
    __tablename__ = "broker_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    account_name = Column(String(100), nullable=True)
    api_key = Column(Text, nullable=True)
    api_secret = Column(Text, nullable=True)
    access_token = Column(Text, nullable=True)
    last_login_trading_day = Column(Date, nullable=True)
    is_connected = Column(Boolean, default=False, nullable=False)
    zerodha_user_name = Column(String(100), nullable=True)
    broker_user_id = Column(String(50), nullable=True)
    oauth_state = Column(String(255), nullable=True)
    oauth_state_created_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # One-to-One relationship back-reference mapping
    user = relationship(
        "User",
        back_populates="broker_account"
    )
