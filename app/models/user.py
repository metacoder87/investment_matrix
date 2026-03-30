from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime, timezone

def utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now_naive)
    
    # 2FA Secret (Future use)
    totp_secret = Column(String, nullable=True)

    # Relationship
    portfolios = relationship("Portfolio", back_populates="user", cascade="all, delete-orphan")
