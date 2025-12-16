"""Database session management."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from origin_api.settings import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url_computed,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

