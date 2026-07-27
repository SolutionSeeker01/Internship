# Backend/dev_tools/drm/event_bus.py
"""
Runtime Event Bus — Thread-Safe Non-Blocking Telemetry Bus

Provides an isolated, in-process pub/sub event transport for monitoring tools.
Guarantees:
  1. Non-blocking publish (`publish` never waits or raises exceptions to caller).
  2. Failure isolation (errors in subscribers are caught and swallowed).
  3. Zero coupling (backend components emit events without knowing subscribers).
  4. Thread safety (safe for multi-threaded trade execution environment).
"""

import queue
import threading
from typing import Callable, List, Optional
from dev_tools.drm.models import RuntimeEvent
from utils.logger import get_logger

logger = get_logger(__name__)

# Type alias for event subscriber callback
SubscriberCallable = Callable[[RuntimeEvent], None]


class RuntimeEventBus:
    """
    Thread-safe, bounded, non-blocking pub/sub event bus.
    """

    def __init__(self, max_queue_size: int = 1000):
        self._subscribers: List[SubscriberCallable] = []
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Starts background worker thread to process queued events."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._worker_thread = threading.Thread(
                target=self._process_queue,
                name="RuntimeEventBusWorker",
                daemon=True
            )
            self._worker_thread.start()
            logger.debug("RuntimeEventBus worker thread started.")

    def stop(self) -> None:
        """Stops background worker thread cleanly."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        # Unblock worker queue cleanly even if full
        while True:
            try:
                self._queue.put_nowait(None)
                break
            except queue.Full:
                try:
                    self._queue.get_nowait()  # Drop oldest item to make space for stop sentinel
                except queue.Empty:
                    break

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
        logger.debug("RuntimeEventBus worker thread stopped.")

    def _ensure_started(self) -> None:
        """Helper to ensure worker thread is running automatically."""
        if not self._running:
            self.start()

    def subscribe(self, callback: SubscriberCallable) -> None:
        """Registers a callback subscriber to receive published events."""
        self._ensure_started()
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: SubscriberCallable) -> None:
        """Removes a registered callback subscriber."""
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def publish(self, event: RuntimeEvent) -> None:
        """
        Publishes a RuntimeEvent to the bus.

        Guarantees non-blocking execution: if queue is full or an exception occurs,
        the error is swallowed to prevent interrupting trading execution.
        """
        if not isinstance(event, RuntimeEvent):
            return

        self._ensure_started()

        try:
            # Non-blocking put; if queue is full, drop event to protect trading engine
            self._queue.put_nowait(event)
        except queue.Full:
            logger.warning(f"RuntimeEventBus queue full ({self._queue.maxsize}). Event dropped: {event.event_type}")
        except Exception as e:
            logger.error(f"RuntimeEventBus unexpected error during publish: {e}")

    def _process_queue(self) -> None:
        """Background worker thread delivering events sequentially to subscribers."""
        while self._running:
            try:
                event = self._queue.get(timeout=0.2)
                if event is None:
                    continue

                with self._lock:
                    current_subscribers = list(self._subscribers)

                for subscriber in current_subscribers:
                    try:
                        subscriber(event)
                    except Exception as sub_err:
                        # Isolated subscriber exception barrier: swallow to protect bus & caller
                        logger.error(f"Error in RuntimeEventBus subscriber '{subscriber}': {sub_err}")

                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"RuntimeEventBus worker exception: {e}")


# Singleton instance for convenient backend event publishing
global_event_bus = RuntimeEventBus()
