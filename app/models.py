from sqlalchemy import Column, String, Text
from database import Base


class Instrument(Base):
    """
    SQLAlchemy model for storing instrument metadata.
    This corresponds to the 'instrument_metadata' table in the SRS.
    """
    __tablename__ = "instrument_metadata"

    symbol = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    exchange = Column(String)
    asset_class = Column(String)
    sector = Column(String)
    description = Column(Text)