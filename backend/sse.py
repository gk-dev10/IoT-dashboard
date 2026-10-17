"""Server-Sent Events (SSE) Pub/Sub manager for real-time telemetry streaming."""

import json
import logging
import queue
import threading

logger = logging.getLogger(__name__)


class SSEManager:
    """Thread-safe Pub/Sub manager for Server-Sent Events subscribers."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers = set()

    def subscribe(self):
        """Register a new subscriber and return its queue."""
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.add(q)
        logger.debug("SSE client connected. Active subscribers: %d", len(self._subscribers))
        return q

    def unsubscribe(self, q):
        """Unregister a subscriber queue."""
        with self._lock:
            self._subscribers.discard(q)
        logger.debug("SSE client disconnected. Active subscribers: %d", len(self._subscribers))

    def broadcast(self, event_name, data):
        """Send an SSE event to all currently connected subscribers."""
        try:
            payload = json.dumps(data)
        except Exception as e:
            logger.error("Failed to JSON-serialize SSE payload: %s", e)
            return

        msg = f"event: {event_name}\ndata: {payload}\n\n"

        with self._lock:
            subscribers_snapshot = list(self._subscribers)

        for q in subscribers_snapshot:
            try:
                q.put_nowait(msg)
            except queue.Full:
                # If subscriber queue is backed up, drain one old message and push new
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except Exception:
                    pass

    def broadcast_comment(self, comment="heartbeat"):
        """Send an SSE comment line (used for heartbeats to keep connection alive)."""
        msg = f": {comment}\n\n"
        with self._lock:
            subscribers_snapshot = list(self._subscribers)

        for q in subscribers_snapshot:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass


# Global singleton instance
sse_manager = SSEManager()
