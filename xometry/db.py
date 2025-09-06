"""
Configurarea bazei de date SQLAlchemy
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from .models import Base

def init_db(database_url: str):
    """Inițializează baza de date"""
    engine = create_engine(database_url)
    Base.metadata.create_all(bind=engine)
    print("Baza de date inițializată cu succes")

def get_db():
    """Returnează o sesiune de bază de date"""
    database_url = 'sqlite:///xometry_offers.db'
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
