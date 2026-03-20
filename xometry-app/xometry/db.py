"""
Configurarea bazei de date SQLAlchemy
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base

_ENGINE = None
_SESSION_LOCAL = None


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///xometry_offers.db")


def _engine_kwargs(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


def get_engine(database_url: str | None = None):
    global _ENGINE, _SESSION_LOCAL

    resolved_url = database_url or get_database_url()
    if _ENGINE is None:
        _ENGINE = create_engine(resolved_url, **_engine_kwargs(resolved_url))
        _SESSION_LOCAL = sessionmaker(autocommit=False, autoflush=False, bind=_ENGINE)
    return _ENGINE


def init_db(database_url: str | None = None):
    """Initializeaza baza de date."""
    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)
    print("Baza de date initializata cu succes")


def get_db():
    """Returneaza o sesiune de baza de date."""
    SessionLocal = _SESSION_LOCAL or sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=get_engine(),
    )
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
