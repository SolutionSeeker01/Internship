import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
from Backend.utils.logger import get_logger

logger = get_logger(__name__)

# Load environment variables from .env file
load_dotenv()

# Retrieve PostgreSQL configurations
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "market_dashboard")

# Validate required credentials
if not DB_USER or not DB_PASSWORD:
    raise ValueError(
        "Missing database credentials. Please ensure both DB_USER and DB_PASSWORD "
        "are specified in your .env file or system environment variables."
    )

# Build standard connection URL using explicit psycopg2 dialect
DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

logger.info(f"Connecting to database host={DB_HOST}:{DB_PORT}, database={DB_NAME}")

try:
    # pool_pre_ping=True tests connection liveness on checkout
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
except Exception as e:
    logger.critical(f"Failed to create database engine: {e}", exc_info=True)
    raise

Base = declarative_base()


def get_db():
    """
    Dependency generator yielding db session and cleaning up connection locks.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
