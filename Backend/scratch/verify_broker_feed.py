import os
import sys

# Ensure backend folder is in PYTHONPATH
sys.path.append(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from services.brokers.zerodha import ZerodhaBroker

print("=== Standalone Broker Feed Verification ===")
try:
    broker = ZerodhaBroker(
        api_key="dummy",
        access_token="dummy"
    )
    print("Successfully instantiated ZerodhaBroker.")
    
    is_running = broker.is_feed_running()
    print(f"broker.is_feed_running() returned: {is_running} (Expected: False)")
    
    print("\nStandalone ZerodhaBroker compilation and execution verification PASSED!")
except Exception as e:
    print(f"\nStandalone ZerodhaBroker verification FAILED with error: {e}")
    sys.exit(1)
