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
from routers.signals import router as signals_router
from routers.instruments import router as instruments_router
from routers.dashboard import router as dashboard_router
from market_data.kite_client import start_market_data_service, register_order_update_callback
from services.brokers.factory import BrokerFactory
from services.runtime.runtime_coordinator import RuntimeCoordinator

# Module-level RuntimeCoordinator singleton.
# Owns: OrderManagerRegistry, BrokerEventRouter, StartupRecoveryService, TickRouter.
# Initialized during lifespan startup; shut down during lifespan shutdown.
_runtime_coordinator: RuntimeCoordinator = RuntimeCoordinator(broker_factory=BrokerFactory)


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
        
        from database.watchlist_repository import init_db as init_watchlists_db
        init_watchlists_db()
        logger.info("Watchlists database schema successfully initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize database schema on startup: {e}")
        raise

    # Load subscription universe from PostgreSQL into RAM cache
    try:
        from market_data.subscriptions import load_instruments
        load_instruments()
        logger.info("Subscription universe successfully loaded from database into RAM.")
    except Exception as e:
        logger.error(f"Failed to load subscription universe at startup: {e}")
        raise

    # --- Startup Runtime Reconstruction for connected MASTERs ---
    try:
        from database.db import SessionLocal
        from models.broker_account import BrokerAccount
        from models.user import User, UserRole
        from security.encryption import decrypt_value
        from services.brokers.factory import BrokerFactory
        from market_data.kite_client import start_market_data_service
        import asyncio

        db = SessionLocal()
        try:
            connected_accounts = db.query(BrokerAccount).join(
                User, User.id == BrokerAccount.user_id
            ).filter(
                User.role == UserRole.MASTER,
                BrokerAccount.is_connected == True
            ).all()
            
            logger.info(f"Startup scan: Found {len(connected_accounts)} connected MASTER accounts to reconstruct.")
            
            for account in connected_accounts:
                try:
                    if not account.api_key or not account.access_token:
                        logger.warning(f"Reconstruction skipped for master user ID {account.user_id}: missing key or access token.")
                        continue
                        
                    api_key = decrypt_value(account.api_key)
                    access_token = decrypt_value(account.access_token)
                    
                    broker = BrokerFactory.get_broker(
                        account.broker,
                        api_key=api_key,
                        access_token=access_token
                    )
                    
                    from datetime import datetime
                    token_time = datetime.combine(account.last_login_trading_day, datetime.min.time()) if account.last_login_trading_day else None
                    if broker.is_token_expired(token_time):
                        logger.warning(f"Reconstruction skipped for master user ID {account.user_id}: broker token has expired. Syncing database connection state to False.")
                        try:
                            account.is_connected = False
                            db.commit()
                        except Exception as db_err:
                            db.rollback()
                            logger.error(f"Failed to commit database update for expired token: {db_err}")
                        continue
                    
                    # Start feed asynchronously using the running loop
                    loop = asyncio.get_running_loop()
                    start_market_data_service(loop, api_key, access_token)
                    logger.info(f"Reconstruction success: Market feed restarted for master user ID {account.user_id}")
                    
                except Exception as rec_err:
                    logger.error(f"Failed to reconstruct session for master user ID {account.user_id}: {rec_err}", exc_info=True)
        finally:
            db.close()
    except Exception as scan_err:
        logger.error(f"Critical error scanning connected MASTERs on startup: {scan_err}")

    # Pre-startup database table counts logging
    try:
        from database.db import SessionLocal
        from sqlalchemy import text
        pre_session = SessionLocal()
        sig_cnt = pre_session.execute(text("SELECT COUNT(*) FROM signals;")).scalar()
        set_cnt = pre_session.execute(text("SELECT COUNT(*) FROM signal_execution_targets;")).scalar()
        trd_cnt = pre_session.execute(text("SELECT COUNT(*) FROM trades;")).scalar()
        ord_cnt = pre_session.execute(text("SELECT COUNT(*) FROM orders;")).scalar()
        logger.info(f"PRE-RECOVERY DB COUNTS -> signals: {sig_cnt}, signal_execution_targets: {set_cnt}, trades: {trd_cnt}, orders: {ord_cnt}")
        pre_session.close()
    except Exception as count_err:
        logger.warning(f"Pre-recovery DB count log failed: {count_err}")

    # Initialize RuntimeCoordinator infrastructure (OrderManagerRegistry, BrokerEventRouter,
    # StartupRecoveryService, TickRouter) and execute startup crash recovery.
    try:
        _runtime_coordinator.initialize()
        recovery_summary = _runtime_coordinator.start()
        logger.info(f"RuntimeCoordinator started. Recovery summary: {recovery_summary}")
    except Exception as coordinator_err:
        logger.error(f"Failed to initialize/start RuntimeCoordinator on startup: {coordinator_err}", exc_info=True)
        # Non-fatal: log and continue. Live fills won't be tracked but entry pipeline is unaffected.

    # Register the broker order update callback BEFORE start_market_data_service() is called.
    # This wires the KiteTicker on_order_update stream →  BrokerEventRouter → OrderManagerService,
    # so broker fill/rejection events update the orders table from PLACED → COMPLETE.
    try:
        broker_event_router = _runtime_coordinator.get_broker_event_router()
        register_order_update_callback(broker_event_router.process_broker_event)
        logger.info("Order update callback registered: KiteTicker on_order_update → BrokerEventRouter.")
    except Exception as cb_err:
        logger.error(f"Failed to register order update callback: {cb_err}", exc_info=True)
        # Non-fatal: entry pipeline still functions; live fills simply won't auto-update.

    # Start Execution Dispatcher background worker thread
    try:
        from services.execution_dispatcher import global_execution_dispatcher
        global_execution_dispatcher.start()
        logger.info("Execution Dispatcher background worker successfully started.")
    except Exception as disp_err:
        logger.error(f"Failed to start Execution Dispatcher on startup: {disp_err}")

    yield  # Hand over control to run the FastAPI server

    # ── Shutdown sequence ────────────────────────────────────────────────────
    # 1. Signal broker dispatcher threads to exit backoff waits immediately.
    #    Must happen BEFORE stopping the dispatcher thread so in-flight transient
    #    retries don't hold the thread for up to 4 s after stop() is called.
    try:
        from services.broker_dispatcher import dispatcher_request_shutdown
        dispatcher_request_shutdown()
        logger.info("Broker dispatcher shutdown signal sent.")
    except Exception as ds_err:
        logger.error(f"Error sending dispatcher shutdown signal: {ds_err}")

    # 2. Stop Execution Dispatcher polling loop.
    try:
        from services.execution_dispatcher import global_execution_dispatcher
        logger.info("Stopping Execution Dispatcher during application shutdown...")
        global_execution_dispatcher.stop()
    except Exception as disp_stop_err:
        logger.error(f"Error stopping Execution Dispatcher during shutdown: {disp_stop_err}")

    # 3. Shut down RuntimeCoordinator (registry, event router, tick router cleanup).
    try:
        _runtime_coordinator.shutdown()
        logger.info("RuntimeCoordinator shut down cleanly.")
    except Exception as rc_err:
        logger.error(f"Error shutting down RuntimeCoordinator: {rc_err}")

    # 4. Stop market data feed.
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
from routers.watchlist import router as watchlist_router
from routers.client_dashboard import router as client_dashboard_router
from routers.strategy_management import router as strategy_management_router
from routers.client_strategies import router as client_strategies_router
from routers.dev_telemetry import router as dev_telemetry_router
from fastapi import Request
from fastapi.responses import JSONResponse
from exceptions import PlatformException

# Register the WebSocket route handler
app.include_router(ws_router)
app.include_router(candle_router)
app.include_router(webhook_router)
app.include_router(signals_router)
app.include_router(instruments_router)
app.include_router(dashboard_router)
app.include_router(auth_router)
app.include_router(user_management_router)
app.include_router(watchlist_router)
app.include_router(client_dashboard_router)
app.include_router(strategy_management_router)
app.include_router(client_strategies_router)
app.include_router(dev_telemetry_router)


@app.exception_handler(PlatformException)
async def platform_exception_handler(request: Request, exc: PlatformException):
    """
    Global exception handler for all custom PlatformExceptions.
    Translates exception metadata into standard HTTP JSONResponse structures.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.error_code,
                "message": exc.client_message
            }
        }
    )


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
