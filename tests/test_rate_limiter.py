import unittest

from rate_limiter import SlidingWindowLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class SlidingWindowLimiterTests(unittest.TestCase):
    def test_allows_up_to_the_limit(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(3, 3600, clock=clock)
        self.assertTrue(limiter.acquire(timeout=0))
        self.assertTrue(limiter.acquire(timeout=0))
        self.assertTrue(limiter.acquire(timeout=0))
        self.assertFalse(limiter.acquire(timeout=0))
        self.assertEqual(limiter.used(), 3)
        self.assertEqual(limiter.available(), 0)

    def test_slots_expire_after_the_window(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(2, 60, clock=clock)
        limiter.acquire(timeout=0)
        limiter.acquire(timeout=0)
        self.assertFalse(limiter.acquire(timeout=0))
        clock.advance(61)
        self.assertTrue(limiter.acquire(timeout=0))
        self.assertEqual(limiter.used(), 1)

    def test_waiting_consumes_a_slot_when_one_frees_up(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(1, 60, clock=clock)
        limiter.acquire(timeout=0)
        self.assertFalse(limiter.acquire(timeout=0))
        clock.advance(60)
        self.assertTrue(limiter.acquire(timeout=0))

    def test_zero_limit_disables_the_guard(self):
        limiter = SlidingWindowLimiter(0, 3600)
        self.assertTrue(limiter.acquire(timeout=0))
        self.assertTrue(limiter.acquire(timeout=0))
        self.assertEqual(limiter.state()["limit"], 0)

    def test_state_reports_the_next_free_slot(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(1, 100, clock=clock)
        limiter.acquire(timeout=0)
        state = limiter.state()
        self.assertEqual(state["used"], 1)
        self.assertEqual(state["remaining"], 0)
        self.assertAlmostEqual(state["next_slot_in_seconds"], 100, delta=1)

    def test_acquire_returns_false_when_the_wait_times_out(self):
        clock = FakeClock()
        limiter = SlidingWindowLimiter(1, 3600, clock=clock)
        limiter.acquire(timeout=0)
        self.assertFalse(limiter.acquire(timeout=0))


if __name__ == "__main__":
    unittest.main()
