"""
Modelele SQLAlchemy pentru baza de date
"""
from sqlalchemy import Column, Integer, Float, String, Text, DateTime, ForeignKey
from sqlalchemy.types import JSON  # dacă baza/driverul permite; altfel comentează și folosește Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class Offer(Base):
    """Model pentru oferte"""
    __tablename__ = "offers"
    
    id = Column(Integer, primary_key=True, index=True)
    offer_id = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=True)
    customer = Column(String, nullable=True)
    url = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relație cu reperele
    parts = relationship("Part", back_populates="offer", cascade="all, delete-orphan")

class Part(Base):
    """Model pentru reperele ofertei"""
    __tablename__ = "parts"
    
    id = Column(Integer, primary_key=True, index=True)
    offer_id = Column(Integer, ForeignKey("offers.id"), nullable=False)
    part_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    material = Column(String, nullable=True)
    remarks = Column(Text, nullable=True)
    weight = Column(Float, nullable=True)
    length = Column(Float, nullable=True)
    width = Column(Float, nullable=True)
    height = Column(Float, nullable=True)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, nullable=True)
    discount = Column(Float, default=0.0)
    lead_time = Column(Integer, nullable=True)
    total_price = Column(Float, nullable=True)
    image_url = Column(String(500))  # URL-ul imaginii reperului
    
    # Relație cu oferta
    offer = relationship("Offer", back_populates="parts")
    processes = Column(JSON, nullable=True)  # dacă nu merge, folosește: Text și serializezi manual
    volume_cm3 = Column(Float, nullable=True)

class Attachment(Base):
    """Model pentru atașamente"""
    __tablename__ = "attachments"
    
    id = Column(Integer, primary_key=True, index=True)
    offer_id = Column(Integer, ForeignKey("offers.id"), nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
