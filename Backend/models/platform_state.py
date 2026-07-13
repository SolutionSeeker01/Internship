from sqlalchemy import Column, Integer, SmallInteger, DateTime, ForeignKey, func
from database.db import Base

class PlatformState(Base):
    __tablename__ = "platform_state"

    id = Column(SmallInteger, primary_key=True, default=1)
    active_master_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
