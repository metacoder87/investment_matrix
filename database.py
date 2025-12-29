from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from contextlib import contextmanager
from app.config import settings

Base = declarative_base()
engine = None
SessionLocal = None

def init_db():
    global engine
    global SessionLocal
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        echo=False,  # Set to True to see generated SQL
    )
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine
    )


def get_db():
    if SessionLocal is None:
        init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    """
    Provide a transactional scope around a series of operations.
    """
    if SessionLocal is None:
        init_db()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
