import asyncio
import base64
import unittest

from image_handler import upload_openai_image


class FakeAPI:
    def __init__(self):
        self.calls = []

    async def upload_bytes(self, filename, content, content_type):
        self.calls.append((filename, content, content_type))
        return {
            "uuid": "00000000-0000-0000-0000-000000000123",
            "pathname": filename,
            "contentType": content_type,
        }


class ImageHandlerTests(unittest.TestCase):
    def test_data_url_is_uploaded_as_image_uuid(self):
        api = FakeAPI()
        result = asyncio.run(upload_openai_image(
            api,
            "data:image/png;base64," + base64.b64encode(b"png").decode("ascii"),
        ))
        self.assertEqual(result["uuid"], "00000000-0000-0000-0000-000000000123")
        self.assertEqual(result["contentType"], "image/png")
        self.assertEqual(api.calls[0][1], b"png")

    def test_invalid_scheme_is_rejected(self):
        with self.assertRaises(ValueError):
            asyncio.run(upload_openai_image(FakeAPI(), "file:///tmp/image.png"))


if __name__ == "__main__":
    unittest.main()
