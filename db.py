from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base

load_dotenv()

_DB_PATH = os.environ.get("COMPLETE_AI_DB_PATH", "data/complete_ai.db")
_DB_URL_ENV = os.environ.get("COMPLETE_AI_DB_URL")

# Ensure the SQLite parent directory exists on fresh environments/CI.
if not _DB_URL_ENV:
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)

_DB_URL = _DB_URL_ENV or f"sqlite:///{_DB_PATH}"

_engine = create_engine(
    _DB_URL,
    connect_args={"check_same_thread": False} if _DB_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def get_engine():
    return _engine


def init_db(drop: bool = False):
    if drop:
        Base.metadata.drop_all(_engine)
    Base.metadata.create_all(_engine)


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
