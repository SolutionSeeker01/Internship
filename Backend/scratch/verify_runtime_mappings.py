import os
import sys

# Ensure backend folder is in PYTHONPATH
sys.path.append(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from database.db import SessionLocal
from database.defaults import DEFAULT_SYMBOLS
from market_data.subscriptions import load_instruments, get_instrument_metadata, get_symbol
from market_data.universe import load_universe_cache, get_instrument_token, get_symbol_exchange
from market_data.store import get_market_data, update_market_data
from market_data.kite_client import normalize_tick

print("=== Starting Runtime Mapping Verification ===")

# 1. Initialize databases and caches
load_instruments()
load_universe_cache()

# 2. Trace mappings for target symbols
symbols_to_trace = ["BANKNIFTY", "NIFTY50", "RELIANCE", "INFY", "NIFTY BANK", "NIFTY 50"]

print("\n--- Phase 1: Symbol to Token & Exchange Mapping (from Registry) ---")
resolved_mappings = {}
for sym in symbols_to_trace:
    token = get_instrument_token(sym)
    exchange = get_symbol_exchange(sym)
    print(f"Symbol: {sym:<12} -> Token: {str(token):<8} -> Exchange: {str(exchange)}")
    if token:
        resolved_mappings[sym] = {"token": token, "exchange": exchange}

# 3. Simulate raw tick stream for these tokens
print("\n--- Phase 2: Simulating Raw Ticks and Normalization ---")
simulated_ticks = [
    {"instrument_token": 260105, "last_price": 57938.50, "ohlc": {"open": 57800.0, "high": 58000.0, "low": 57700.0, "close": 57900.0}, "volume": 500000}, # Nifty Bank token
    {"instrument_token": 256265, "last_price": 24200.10, "ohlc": {"open": 24100.0, "high": 24300.0, "low": 24050.0, "close": 24150.0}, "volume": 1200000}, # Nifty 50 token
    {"instrument_token": 738561, "last_price": 2450.00, "ohlc": {"open": 2440.0, "high": 2465.0, "low": 2435.0, "close": 2438.0}, "volume": 1500000},  # Reliance token
    {"instrument_token": 408065, "last_price": 1560.25, "ohlc": {"open": 1550.0, "high": 1570.0, "low": 1545.0, "close": 1555.0}, "volume": 800000}    # Infosys token
]

for raw_tick in simulated_ticks:
    token = raw_tick["instrument_token"]
    # Look up metadata from subscriptions loader
    meta = get_instrument_metadata(token)
    if not meta:
        print(f"No metadata found for token {token}")
        continue
    
    symbol = meta["symbol"]
    exchange = meta["exchange"]
    
    # Run normalize_tick
    normalized = normalize_tick(raw_tick, symbol, exchange)
    key = normalized["key"]
    
    print(f"Raw Tick Token: {token:<8} -> Symbol: {symbol:<10} -> Normalized Key: {key:<14} -> LTP: {normalized['ltp']}")
    
    # Store it
    update_market_data(key, normalized)

# 4. Inspect store contents and keys
print("\n--- Phase 3: Inspecting Store Keys and Payload Keys ---")
store = get_market_data()
for key, payload in store.items():
    print(f"Store Key: {key:<15} -> Payload Symbol: {payload['symbol']:<12} -> Payload Exchange: {payload['exchange']:<6} -> LTP: {payload['ltp']}")

# 5. Assertions & Proofs
print("\n--- Phase 4: Proving Mapping Integrity ---")
collision_detected = False
seen_symbols = set()
for key, payload in store.items():
    symbol = payload["symbol"]
    if symbol in seen_symbols:
        collision_detected = True
    seen_symbols.add(symbol)

print(f"1. No instrument collision occurs: {not collision_detected}")
print(f"2. No two instruments overwrite same store key: {len(store) == len(simulated_ticks)}")

# Specifically verify BANKNIFTY and RELIANCE mappings
reliance_data = store.get("NSE:RELIANCE")
banknifty_data = store.get("NSE:BANKNIFTY")
niftybank_data = store.get("NSE:NIFTY BANK")

if reliance_data:
    print(f"3. NSE:RELIANCE maps strictly to symbol: {reliance_data['symbol']} (Expected: RELIANCE)")
else:
    print("3. NSE:RELIANCE not present in store.")

if banknifty_data:
    print(f"4. NSE:BANKNIFTY maps strictly to symbol: {banknifty_data['symbol']} (Expected: BANKNIFTY)")
elif niftybank_data:
    # Check if NIFTY BANK is the mapped symbol in database
    print(f"4. Note: Database uses canonical name '{niftybank_data['symbol']}' for Nifty Bank token (260105). Key: {niftybank_data['key']}")
else:
    print("4. Index token (260105) not present in store.")
