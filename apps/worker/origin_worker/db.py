"""Database session for worker."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from origin_worker.settings import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url_computed,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

