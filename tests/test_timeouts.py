import unittest

from config.config import FS_CHAT_TOTAL_TIMEOUT, REQUEST_TIMEOUT, SSE_TIMEOUT


class TimeoutConfigurationTests(unittest.TestCase):
    def test_long_model_requests_have_finite_layered_limits(self):
        self.assertEqual(REQUEST_TIMEOUT, 120)
        self.assertEqual(SSE_TIMEOUT.connect, 30)
        self.assertEqual(SSE_TIMEOUT.read, 1200)
        self.assertEqual(SSE_TIMEOUT.write, 60)
        self.assertEqual(SSE_TIMEOUT.pool, 30)
        self.assertEqual(FS_CHAT_TOTAL_TIMEOUT, 1800)
        self.assertGreater(FS_CHAT_TOTAL_TIMEOUT, SSE_TIMEOUT.read)


if __name__ == "__main__":
    unittest.main()
