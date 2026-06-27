from contextlib import asynccontextmanager
from typing import Dict
from fastapi import FastAPI

# Initialize environment variables from .env file at absolute startup
import os
from dotenv import load_dotenv
# Look for .env first in parent directory (workspace root) then locally in Backend/
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
load_dotenv()

# Initialize centralized logging before importing local modules that define their own loggers
from utils.logger import get_logger, setup_logging
setup_logging()
logger = get_logger(__name__)

# Local imports
import models  # Register ORM models for metadata relationships
from routers.websocket import router as ws_router
from routers.candles import router as candle_router
from routers.webhook import router as webhook_router
from routers.instruments import router as instruments_router
from routers.dashboard import router as dashboard_router
from market_data.kite_client import start_market_data_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Asynchronous context manager to manage application startup and shutdown events.
    
    FastAPI lifespan events are the modern, recommended approach replacing 
    deprecated @app.on_event("startup"/"shutdown") handlers.
    """
    logger.info("Starting up FastAPI application lifespan context...")
    
    # Initialize database schemas
    try:
        from database.signal_repository import init_db as init_signals_db
        init_signals_db()
        logger.info("Signals database schema successfully initialized.")
        
        from database.instrument_repository import init_db as init_instruments_db
        init_instruments_db()
        logger.info("Instruments database schema successfully initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize database schema on startup: {e}")
        raise

    # Load active instruments from PostgreSQL into RAM cache
    try:
        from market_data.subscriptions import load_instruments
        load_instruments()
        logger.info("Active instruments successfully loaded from database into RAM.")
    except Exception as e:
        logger.error(f"Failed to load active instruments at startup: {e}")
        raise

    # Load universe cache
    try:
        from market_data.universe import load_universe_cache
        load_universe_cache()
    except Exception as e:
        logger.error(f"Failed to load UNIVERSE_CACHE at startup: {e}")

    # Market data service is now dynamically started upon successful broker callback verification.
    yield  # Hand over control to run the FastAPI server

    # Clean up operations go here (e.g. closing websocket threads/clients if needed)
    try:
        from market_data.kite_client import stop_market_data_service
        logger.info("Stopping market data service during application shutdown")
        stop_market_data_service()
    except Exception as shutdown_err:
        logger.error(f"Error stopping market data service during shutdown: {shutdown_err}")
    logger.info("Shutting down FastAPI application lifespan context...")


from fastapi.middleware.cors import CORSMiddleware

# Create FastAPI application with lifespan configurations
app = FastAPI(
    title="Market Dashboard Backend",
    version="1.0.0",
    description="Real-time market dashboard streaming Zerodha Kite ticks via WebSockets.",
    lifespan=lifespan,
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routers.auth import router as auth_router
from routers.user_management import router as user_management_router

# Register the WebSocket route handler
app.include_router(ws_router)
app.include_router(candle_router)
app.include_router(webhook_router)
app.include_router(instruments_router)
app.include_router(dashboard_router)
app.include_router(auth_router)
app.include_router(user_management_router)


@app.get("/")
def get_root_status() -> Dict[str, str]:
    """
    Root status endpoint.
    
    Returns basic application descriptive metadata.
    """
    return {
        "status": "online",
        "service": "Market Dashboard API",
        "version": "1.0.0",
    }


@app.get("/health")
def health_check() -> Dict[str, str]:
    """
    Health check endpoint.
    
    Used by load balancers, container orchestrators (e.g. Kubernetes), 
    or monitoring scripts to ensure the server process is responsive.
    """
    return {
        "status": "healthy"
    }
