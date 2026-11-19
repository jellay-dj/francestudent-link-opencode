import unittest

from sse_parser import parse_sse_stream_sync


class FakeResponse:
    def __init__(self, lines):
        self.lines = lines

    def iter_lines(self):
        return iter(self.lines)


class SSEParserTests(unittest.TestCase):
    def test_sync_parser_yields_events_progressively(self):
        response = FakeResponse([
            "id: 1",
            "event: stream.open",
            'data: {"chat_id":"chat-1"}',
            "",
            "id: 2",
            "event: response.output_text.delta",
            'data: {"delta":"hello"}',
            "",
        ])
        events = list(parse_sse_stream_sync(response))
        self.assertEqual([event["event"] for event in events], [
            "stream.open",
            "response.output_text.delta",
        ])
        self.assertEqual(events[1]["data"]["delta"], "hello")
        self.assertEqual(events[1]["last_event_id"], "2")


if __name__ == "__main__":
    unittest.main()
