import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import sessionmaker

from models import Base

load_dotenv()
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if os.getenv("RENDER") == "true" and not DATABASE_URL.startswith(
    ("postgres://", "postgresql://", "postgresql+psycopg://")
):
    raise RuntimeError("Render requires a PostgreSQL DATABASE_URL.")

if not DATABASE_URL:
    DATA_DIR.mkdir(exist_ok=True)
    DATABASE_URL = f"sqlite:///{DATA_DIR / 'app.db'}"

options = {"hide_parameters": True}
if DATABASE_URL.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.split("://", 1)[1]
    options.update(pool_pre_ping=True, pool_size=2, max_overflow=1, connect_args={"connect_timeout": 10})

try:
    engine = create_engine(DATABASE_URL, **options)
except (ArgumentError, ValueError):
    raise RuntimeError("Invalid DATABASE_URL. Check the database settings.") from None
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_session():
    return SessionLocal()


if __name__ == "__main__":
    init_db()
    print("Database initialized.")
