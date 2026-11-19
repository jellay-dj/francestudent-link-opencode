import unittest

from openai_adapter import (
    extract_openai_images,
    openai_messages_to_text,
    openai_response_to_sse,
)


class OpenAIAdapterTests(unittest.TestCase):
    def test_multimodal_message_preserves_text_and_extracts_images(self):
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AA=="},
                },
            ],
        }]
        text = openai_messages_to_text(messages)
        self.assertEqual(text, "Describe this image")
        self.assertNotIn("[IMAGE]", text)
        self.assertEqual(
            extract_openai_images(messages),
            ["data:image/png;base64,AA=="],
        )

    def test_stream_response_uses_chunk_object(self):
        response = openai_response_to_sse(
            {
                "content": {"text": "hello"},
                "finishedReason": "completed",
                "tokenUsage": {
                    "input_tokens": 2,
                    "output_tokens": 1,
                    "total_tokens": 3,
                },
            },
            model_name="gpt-5.6-sol",
            delta_mode=True,
        )
        self.assertEqual(response["object"], "chat.completion.chunk")
        self.assertEqual(response["choices"][0]["delta"]["content"], "hello")
        self.assertEqual(response["usage"]["total_tokens"], 3)

    def test_non_stream_response_uses_completion_object(self):
        response = openai_response_to_sse(
            {"content": {"text": "hello"}, "finishedReason": "completed"},
            model_name="gpt-5.6-sol",
        )
        self.assertEqual(response["object"], "chat.completion")
        self.assertEqual(response["choices"][0]["message"]["content"], "hello")


if __name__ == "__main__":
    unittest.main()
