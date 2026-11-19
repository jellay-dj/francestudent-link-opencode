"""Track which France Student models are temporarily unusable.

France Student meters some models separately: a model can answer
"France Student a refusé la requête : limite atteinte." while every other
model of the same account works. Retrying the same model wastes a request
and delays the answer, so a model that just failed is parked for a while and
the bridge moves on to the next candidate.
"""

import threading
import time


class ModelHealth:
    """Remember the models that are currently refused by France Student."""

    def __init__(self, block_seconds=900, clock=time.monotonic):
        self.block_seconds = block_seconds
        self._clock = clock
        self._lock = threading.RLock()
        self._blocked = {}

    def block(self, model, seconds=None):
        """Park a model for a while."""
        duration = self.block_seconds if seconds is None else seconds
        with self._lock:
            self._blocked[model] = self._clock() + duration
        return duration

    def clear(self, model):
        with self._lock:
            self._blocked.pop(model, None)

    def is_available(self, model):
        with self._lock:
            until = self._blocked.get(model)
            if until is None:
                return True
            if self._clock() >= until:
                self._blocked.pop(model, None)
                return True
            return False

    def blocked_for(self, model):
        with self._lock:
            until = self._blocked.get(model)
            if until is None:
                return 0
            return max(0, int(until - self._clock()))

    def state(self):
        with self._lock:
            now = self._clock()
            return {
                model: max(0, int(until - now))
                for model, until in self._blocked.items()
                if until > now
            }
