"""End-to-end validation for the France Student bridge."""

import argparse
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path
from urllib.parse import urlparse

import httpx


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TIMEOUT = 240.0


class ValidationError(RuntimeError):
    pass


def load_env_file(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def find_free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def png_chunk(chunk_type, payload):
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def make_solid_green_png():
    width = 64
    height = 64
    rows = []
    for _ in range(height):
        row = bytearray([0])
        for _ in range(width):
            row.extend((0, 255, 0))
        rows.append(bytes(row))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + png_chunk(b"IEND", b"")
    )


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def wait_for_health(base_url, process, timeout=30.0):
    deadline = time.time() + timeout
    with httpx.Client(base_url=base_url, timeout=5.0) as client:
        while time.time() < deadline:
            if process is not None and process.poll() is not None:
                raise ValidationError("Bridge process exited before becoming ready")
            try:
                response = client.get("/health")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.25)
    raise ValidationError(f"Bridge did not become ready at {base_url}")


def content_text(completion):
    message = completion["choices"][0].get("message", {})
    return message.get("content") or ""


def validate_auth_models(client):
    health = client.get("/health")
    require(health.status_code == 200, "/health did not return 200")
    require(health.json().get("authenticated") is True, "France Student auth failed")

    models_response = client.get("/v1/models")
    require(models_response.status_code == 200, "/v1/models did not return 200")
    models = models_response.json().get("data", [])
    require(models, "/v1/models returned no models")
    require(all(item.get("id") for item in models), "A model entry has no ID")

    chats_response = client.get("/chats", params={"limit": 1})
    require(chats_response.status_code == 200, "/chats did not return 200")
    chats = chats_response.json().get("chats", [])
    require(chats, "No persisted France Student chat was available")
    detail = client.get(f"/chat/{chats[0]['id']}")
    require(detail.status_code == 200, "Persisted chat detail could not be loaded")
    return len(models)


def validate_chat_non_streaming(client, model):
    response = client.post("/v1/chat/completions", json={
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "stream": False,
    })
    require(response.status_code == 200, "Non-streaming chat failed")
    completion = response.json()
    require(
        completion.get("object") == "chat.completion",
        "Non-streaming chat has the wrong response type",
    )
    require(content_text(completion).strip(), "Non-streaming chat returned no text")


def validate_chat_streaming(client, model):
    chunks = []
    done_seen = False
    with client.stream("POST", "/v1/chat/completions", json={
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: STREAM"}],
        "stream": True,
    }) as response:
        require(response.status_code == 200, "Streaming chat failed")
        for line in response.iter_lines():
            if line == "data: [DONE]":
                done_seen = True
            elif line.startswith("data: "):
                chunks.append(json.loads(line[6:]))
    require(done_seen, "Streaming chat did not emit data: [DONE]")
    require(chunks, "Streaming chat returned no chunks")
    require(
        all(chunk.get("object") == "chat.completion.chunk" for chunk in chunks),
        "Streaming chat returned a non-chunk object",
    )


def validate_vision(client, model):
    png = make_solid_green_png()
    image_url = (
        "data:image/png;base64,"
        + base64.b64encode(png).decode("ascii")
    )
    response = client.post("/v1/chat/completions", json={
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "What single color fills the entire image? "
                        "Answer with one word."
                    ),
                },
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }],
        "stream": False,
    })
    require(response.status_code == 200, "Vision request failed")
    text = content_text(response.json())
    require(text.strip(), "Vision request returned no analysis")
    require("[IMAGE]" not in text, "Vision input was replaced by a placeholder")
    require("green" in text.lower(), "Vision analysis missed the green image")


def validate_image_generation(client):
    response = client.post("/v1/images/generations", json={
        "model": "gpt-image-1",
        "prompt": (
            "A single solid red circle perfectly centered on a plain white "
            "square background, no text, no shadow."
        ),
        "n": 1,
        "size": "1024x1024",
        "response_format": "url",
    })
    require(response.status_code == 200, "Image generation failed")
    items = response.json().get("data", [])
    require(items, "Image generation returned no item")
    image_url = items[0].get("url")
    require(image_url, "Generated image has no local URL")

    image_response = client.get(image_url)
    require(image_response.status_code == 200, "Generated image URL is not downloadable")
    require(
        image_response.headers.get("content-type", "").startswith("image/"),
        "Generated image URL did not return an image",
    )
    require(len(image_response.content) > 1000, "Generated image is unexpectedly small")

    filename = Path(urlparse(image_url).path).name
    local_path = BASE_DIR / "storage" / "images" / filename
    require(local_path.exists(), "Generated image was not stored locally")
    require(local_path.stat().st_size == len(image_response.content), "Local image size mismatch")


def run_validation(base_url):
    model = os.environ.get("FS_IMAGE_MODEL", "gpt-5.6-sol")
    with httpx.Client(
        base_url=base_url,
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    ) as client:
        checks = [
            ("authentication and model catalogue", lambda: validate_auth_models(client)),
            ("non-streaming chat", lambda: validate_chat_non_streaming(client, model)),
            ("streaming chat", lambda: validate_chat_streaming(client, model)),
            ("vision", lambda: validate_vision(client, model)),
            ("image generation", lambda: validate_image_generation(client)),
        ]
        for label, check in checks:
            started = time.monotonic()
            try:
                result = check()
            except Exception as exc:
                print(f"[FAIL] {label}: {exc}")
                raise
            elapsed = time.monotonic() - started
            suffix = f" ({result} models)" if label.startswith("authentication") else ""
            print(f"[PASS] {label}{suffix} ({elapsed:.2f}s)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        help="Validate an already-running bridge instead of starting one.",
    )
    args = parser.parse_args()

    load_env_file(BASE_DIR / ".env")
    require(
        os.environ.get("FS_EMAIL") and os.environ.get("FS_PASSWORD"),
        "FS_EMAIL and FS_PASSWORD must be configured in .env",
    )

    process = None
    base_url = args.base_url.rstrip("/") if args.base_url else None
    try:
        if base_url is None:
            port = find_free_port()
            base_url = f"http://127.0.0.1:{port}"
            env = os.environ.copy()
            env.update({
                "BIND_HOST": "127.0.0.1",
                "BIND_PORT": str(port),
                "PUBLIC_BASE_URL": base_url,
                "PYTHONIOENCODING": "utf-8",
            })
            process = subprocess.Popen(
                [sys.executable, "bridge_server.py"],
                cwd=BASE_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
            )
        wait_for_health(base_url, process)
        run_validation(base_url)
        print("ALL-PASS")
        return 0
    except Exception as exc:
        print(f"VALIDATION-FAILED: {exc}")
        return 1
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
