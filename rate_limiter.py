"""Client-side quota management for France Student requests.

France Student publishes hard limits (50 new chats per day, a rolling
hourly message budget and a monthly chat budget). The bridge stays below
them on purpose:

* every outbound message passes through :class:`SlidingWindowLimiter`, so a
  burst of OpenCode turns cannot outrun the upstream quota;
* auxiliary requests that do not need the model (session titles) are served
  locally, which removes one message per session.

The limiter never drops a request silently: when the budget is exhausted it
waits for a slot, and only then reports that the wait was too long.
"""

import threading
import time


class SlidingWindowLimiter:
    """Allow at most ``limit`` events in any ``window_seconds`` period."""

    def __init__(self, limit, window_seconds=3600.0, clock=time.monotonic):
        self.limit = max(0, int(limit))
        self.window = float(window_seconds)
        self._clock = clock
        self._lock = threading.Condition()
        self._events = []

    def _prune(self, now):
        threshold = now - self.window
        if self._events and self._events[0] <= threshold:
            self._events = [stamp for stamp in self._events if stamp > threshold]

    def available(self):
        with self._lock:
            self._prune(self._clock())
            return max(0, self.limit - len(self._events))

    def used(self):
        with self._lock:
            self._prune(self._clock())
            return len(self._events)

    def wait_time(self):
        """Seconds until the next slot becomes free."""
        with self._lock:
            if self.limit == 0:
                return float("inf")
            self._prune(self._clock())
            if len(self._events) < self.limit:
                return 0.0
            return max(0.0, self._events[0] + self.window - self._clock())

    def acquire(self, timeout=None):
        """Consume one slot, waiting for it when needed.

        Returns True when a slot was consumed, False when the wait timed out.
        """
        if self.limit == 0:
            return True
        deadline = None if timeout is None else self._clock() + timeout
        with self._lock:
            while True:
                now = self._clock()
                self._prune(now)
                if len(self._events) < self.limit:
                    self._events.append(now)
                    return True
                if deadline is not None and now >= deadline:
                    return False
                wait = max(0.05, self._events[0] + self.window - now)
                if deadline is not None:
                    wait = min(wait, max(0.0, deadline - now))
                self._lock.wait(wait)

    def state(self):
        with self._lock:
            self._prune(self._clock())
            return {
                "limit": self.limit,
                "window_seconds": self.window,
                "used": len(self._events),
                "remaining": max(0, self.limit - len(self._events)),
                "next_slot_in_seconds": round(self.wait_time(), 1),
            }
