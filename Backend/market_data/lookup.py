import time
from typing import Optional, Dict, Tuple
import threading

from market_data.store import get_symbol_exchange_data
from utils.logger import get_logger

logger = get_logger(__name__)

class BrokerUnavailableException(Exception):
    """Exception raised when the broker service is offline or throws an error during LTP check."""
    pass

# Thread-safe lock for cache access
_cache_lock = threading.Lock()

# In-memory cache for symbol LTP. Key: symbol (uppercase), Value: (ltp, epoch_seconds_timestamp)
_LTP_CACHE: Dict[str, Tuple[float, float]] = {}
CACHE_TTL_SECONDS = 30.0


def get_master_broker():
    """
    Resolves the MASTER user's broker configuration dynamically.
    Falls back to the first available user if no MASTER user is configured.
    """
    from database.db import SessionLocal
    from models.user import User, UserRole
    from models.broker_account import BrokerAccount
    from security.encryption import decrypt_value
    from services.brokers.factory import BrokerFactory

    session = SessionLocal()
    try:
        # 1. Resolve Master User or Fallback
        master_user = session.query(User).filter(User.role == UserRole.MASTER).first()
        if not master_user:
            master_user = session.query(User).first()

        if not master_user:
            logger.error("No platform users configured to establish broker validation context.")
            return None

        # 2. Retrieve Master BrokerAccount
        # Look up all connected broker accounts for the master user
        connected_accounts = session.query(BrokerAccount).filter(
            BrokerAccount.user_id == master_user.id,
            BrokerAccount.is_connected == True
        ).all()

        if len(connected_accounts) > 1:
            logger.error(
                f"Multiple connected broker accounts exist for the MASTER user '{master_user.username}'. "
                "Unable to deterministically choose validation broker context."
            )
            return None
        elif len(connected_accounts) == 1:
            account = connected_accounts[0]
        else:
            # Fall back to the first available broker account configuration for this user
            account = session.query(BrokerAccount).filter(
                BrokerAccount.user_id == master_user.id
            ).first()

        if not account or not account.api_key:
            logger.error(f"Broker credentials not configured for user '{master_user.username}'.")
            return None

        # 3. Decrypt credentials & instantiate
        api_key = decrypt_value(account.api_key)
        access_token = decrypt_value(account.access_token) if account.access_token else None

        return BrokerFactory.get_broker(
            account.broker,
            api_key=api_key,
            access_token=access_token
        )
    except Exception as e:
        logger.error(f"Failed to initialize master validation broker: {e}")
        return None
    finally:
        session.close()


def get_market_price(symbol: str) -> Optional[float]:
    """
    Authoritative helper to retrieve the last traded price (LTP) for a symbol.
    Checks the resolved exchange (NSE/NFO/etc.) in the live cache first, then queries resolved Master broker.
    
    Returns:
        Optional[float]: The last traded price if found, otherwise None.
    """
    from market_data.universe import get_symbol_exchange
    sym_upper = symbol.upper().strip()
    exch_resolved = get_symbol_exchange(sym_upper)
    now = time.time()
    
    # 1. Check live memory store for resolved exchange LTP first (Fast path)
    try:
        store_data = get_symbol_exchange_data(sym_upper, exch_resolved)
        if store_data and store_data.get("ltp") is not None:
            ltp = store_data["ltp"]
            if isinstance(ltp, (int, float)) and ltp > 0:
                logger.debug(f"LTP live store hit for {sym_upper} ({exch_resolved}): {ltp}")
                return ltp
    except Exception as e:
        logger.warning(f"Error checking live store for {sym_upper} ({exch_resolved}): {e}")
 
    # 2. Check local TTL cache
    with _cache_lock:
        if sym_upper in _LTP_CACHE:
            cached_price, cached_time = _LTP_CACHE[sym_upper]
            if now - cached_time < CACHE_TTL_SECONDS:
                logger.debug(f"LTP TTL cache hit for {sym_upper} ({exch_resolved}): {cached_price}")
                return cached_price
            
    # 3. Cache miss - query active Master Broker dynamically using resolved exchange
    try:
        broker = get_master_broker()
        if not broker:
            raise BrokerUnavailableException("Master broker instance unavailable.")

        query_symbol = f"{exch_resolved}:{sym_upper}"
        ltp_res = broker.get_ltp([query_symbol])
        
        if ltp_res and query_symbol in ltp_res and ltp_res[query_symbol].get("last_price") is not None:
            price = ltp_res[query_symbol]["last_price"]
            if isinstance(price, (int, float)) and price > 0:
                # Store in TTL cache and return
                with _cache_lock:
                    _LTP_CACHE[sym_upper] = (price, now)
                logger.info(f"Authoritative live LTP lookup succeeded for {sym_upper} ({exch_resolved}): {price}")
                return price
                        
        logger.warning(f"LTP lookup returned no valid price for {sym_upper} on {exch_resolved}.")
    except Exception as e:
        logger.warning(f"Failed authoritative live market price lookup for {sym_upper} ({exch_resolved}): {e}")
        raise BrokerUnavailableException(str(e))
        
    return None
