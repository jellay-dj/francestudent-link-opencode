import base64
import re
import uuid
import aiofiles
from pathlib import Path
from datetime import datetime
import httpx
from config.config import (
    IMAGES_DIR,
    MAX_IMAGE_DOWNLOAD_BYTES,
    MAX_UPLOAD_BYTES,
    PUBLIC_BASE_URL,
)


DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", re.DOTALL)


def _sanitize(s, max_len=8):
    if not s:
        return "unknown"
    return str(s).replace("/", "_").replace("\\", "_").replace("..", "_").replace(" ", "_")[:max_len]


def generate_filename(chat_id, message_id, image_id, ext="png"):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (
        f"{_sanitize(chat_id)}_{_sanitize(message_id)}_"
        f"{_sanitize(image_id)}_{ts}_{uuid.uuid4().hex[:6]}.{ext}"
    )


def _extension_for_content_type(content_type):
    ext = "png"
    if content_type:
        ct = content_type.lower()
        if "jpeg" in ct or "jpg" in ct:
            ext = "jpg"
        elif "webp" in ct:
            ext = "webp"
        elif "gif" in ct:
            ext = "gif"
        elif "svg" in ct:
            ext = "svg"
    return ext


async def download_and_save_image(api, chat_id, message_id, image_id):
    content, content_type = await api.get_image(chat_id, message_id, image_id)

    filename = generate_filename(
        chat_id,
        message_id,
        image_id,
        _extension_for_content_type(content_type),
    )
    filepath = IMAGES_DIR / filename

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(content)

    return {
        "imageId": image_id,
        "messageId": message_id,
        "chatId": chat_id,
        "localPath": str(filepath.absolute()),
        "filename": filename,
        "downloadUrl": f"{PUBLIC_BASE_URL}/images/{filename}",
        "contentType": content_type,
        "sizeBytes": len(content),
    }


async def download_images_from_output(api, output, server_host=None, server_port=None):
    images = []
    image_items = output.get("imageItems", [])

    chat_id = output.get("chatId")
    message_id = output.get("messageId")
    completed_msg = output.get("completedMessage") or {}

    if not message_id and completed_msg.get("id"):
        message_id = completed_msg["id"]

    seen = set()
    for item in image_items:
        if not item.get("done"):
            continue

        image_id = item.get("id") or item.get("image_id") or item.get("file_id")
        if not image_id or image_id in seen:
            continue

        if str(image_id).startswith("ig_"):
            continue

        seen.add(image_id)

        try:
            result = await download_and_save_image(api, chat_id, message_id, image_id)
            images.append(result)
        except Exception as e:
            images.append({
                "imageId": image_id,
                "error": str(e),
            })

    return images


async def upload_openai_image(api, image_url):
    """Fetch an OpenAI image_url and upload it to France Student."""
    if isinstance(image_url, dict):
        image_url = image_url.get("url", "")
    if not isinstance(image_url, str) or not image_url:
        raise ValueError("image_url must contain a URL or data URL")

    match = DATA_URL_RE.match(image_url)
    if match:
        try:
            content = base64.b64decode(match.group("data"), validate=True)
        except Exception as exc:
            raise ValueError("Invalid base64 image data") from exc
        content_type = match.group("mime")
        filename = f"openai-input.{_extension_for_content_type(content_type)}"
    elif image_url.startswith(("http://", "https://")):
        async with httpx.AsyncClient(
            timeout=60,
            follow_redirects=True,
        ) as client:
            async with client.stream("GET", image_url) as response:
                response.raise_for_status()
                content_type = response.headers.get(
                    "content-type",
                    "image/png",
                ).split(";")[0]
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_IMAGE_DOWNLOAD_BYTES:
                        raise ValueError(
                            "Input image exceeds MAX_IMAGE_DOWNLOAD_BYTES"
                        )
                    chunks.append(chunk)
                content = b"".join(chunks)
        filename = f"openai-input.{_extension_for_content_type(content_type)}"
    else:
        raise ValueError("image_url must use http://, https:// or a data URL")

    if not content_type.startswith("image/"):
        raise ValueError("Input URL did not return an image")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Input image exceeds MAX_UPLOAD_BYTES")

    result = await api.upload_bytes(filename, content, content_type)
    file_uuid = result.get("uuid") or result.get("id")
    if not file_uuid:
        raise ValueError("France Student upload did not return an image UUID")
    return {
        "uuid": file_uuid,
        "filename": result.get("pathname", filename),
        "contentType": result.get("contentType", content_type),
        "sizeBytes": len(content),
    }
