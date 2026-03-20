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
    remarks = Column(Text, nullable=True)  # Observații la nivel de ofertă
    documentation_path = Column(String(500), nullable=True)  # Calea către documentația descărcată
    dosar_id = Column(String, nullable=True)  # ID-ul dosarului alocat
    dosar_path = Column(String(500), nullable=True)  # Calea către dosarul alocat
    dosar_allocated = Column(DateTime, nullable=True)  # Data alocării dosarului
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
    local_image_path = Column(String(500))  # Calea locală către imaginea salvată
    # Deviz per reper
    deviz_path = Column(String(500), nullable=True)  # Cale relativă către devizul XLSX copiat din șablon
    deviz_url = Column(String(500), nullable=True)   # Link extern (ex: Google Sheets) dacă este încărcat
    
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

class Order(Base):
    """Model pentru istoricul comenzilor"""
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String, index=True, nullable=False) # Xometry Order ID
    part_id = Column(String, index=True, nullable=True)   # Xometry Part ID (dacă e detectat)
    status = Column(String, nullable=True)
    order_date = Column(String, nullable=True)
    price = Column(String, nullable=True)
    local_image_path = Column(String(500), nullable=True)
    details = Column(JSON, nullable=True) # Full row data dump
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
