import base64
import json
import os
import time
import uuid
from pathlib import Path
from flask import Flask, request, jsonify, Response, send_file, stream_with_context
from config.config import (
    SERVER_HOST, SERVER_PORT, IMAGES_DIR, DEFAULT_AGENT_ID, DEFAULT_IMAGE_AGENT_ID,
    DEFAULT_IMAGE_MODEL, MAX_RETRIES, RETRY_DELAYS, MAX_UPLOAD_BYTES, FS_ACTION_AGENT,
    FS_TEST_AGENT,
)
from auth import AuthManager
from api_client import FranceStudentAPI
from agentic_bridge import (
    AgenticBridge,
    BridgeError,
    _run_async,
    chat_limiter,
    message_limiter,
    model_health,
)
from fs_status import fetch_status
from fs_actions import report_refresh, test_connection
from sse_parser import extract_output_from_events
from image_handler import download_images_from_output, upload_openai_image
from openai_adapter import (
    extract_openai_images,
    openai_messages_to_text,
    openai_response_to_sse,
)
from model_catalog import (
    canonical_model_name,
    default_agent,
    openai_model_entry,
    resolve_agent,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

auth = AuthManager()
api = FranceStudentAPI(auth)
agentic_bridge = AgenticBridge(api, lambda: _refresh_models())

CACHED_MODELS = []
MODELS_LAST_FETCH = 0


def _refresh_models(force=False):
    global CACHED_MODELS, MODELS_LAST_FETCH
    if force or not CACHED_MODELS or time.time() - MODELS_LAST_FETCH > 3600:
        CACHED_MODELS = _run_async(api.get_models())
        MODELS_LAST_FETCH = time.time()
    return CACHED_MODELS


def _get_default_agent_id():
    try:
        models = _refresh_models()
    except Exception:
        models = CACHED_MODELS
    resolved = default_agent(models)
    if resolved is not None:
        return resolved
    return DEFAULT_AGENT_ID


def _resolve_agent_id(agent_id, strict=False):
    """Resolve an OpenAI model name, France Student name or agent ID."""
    try:
        models = _refresh_models()
    except Exception:
        models = CACHED_MODELS
    resolved = resolve_agent(agent_id, models)
    if resolved is not None:
        return resolved
    if strict:
        return None
    return default_agent(models) or DEFAULT_AGENT_ID


async def _upload_openai_images(image_urls):
    uploaded = []
    for image_url in image_urls:
        uploaded.append(await upload_openai_image(api, image_url))
    return uploaded


def _image_generation_prompt(prompt, size=None, quality=None):
    details = [
        "Generate one image with the image generation tool.",
        "Do not describe the image and do not return a placeholder.",
        f"Image prompt: {prompt}",
    ]
    if size:
        details.append(f"Requested canvas size: {size}.")
    if quality:
        details.append(f"Requested quality: {quality}.")
    return "\n".join(details)


def _openai_chunk(response_id, created, model_name, delta=None,
                  finish_reason=None, usage=None):
    payload = {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_name,
        "choices": [{
            "index": 0,
            "delta": delta or {},
            "finish_reason": finish_reason,
        }],
    }
    if usage is not None:
        payload["usage"] = usage
    return payload


def _openai_usage(output):
    token_usage = output.get("tokenUsage") or {}
    prompt_tokens = (
        token_usage.get("input_tokens")
        or token_usage.get("promptTokenCount")
        or 0
    )
    completion_tokens = (
        token_usage.get("output_tokens")
        or token_usage.get("candidatesTokenCount")
        or 0
    )
    total_tokens = (
        token_usage.get("total_tokens")
        or token_usage.get("totalTokenCount")
        or prompt_tokens + completion_tokens
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def generate_openai_real_stream(text, agent_id, image_ids, model_name,
                                enable_web_search=False):
    response_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    events = []
    sent_text = []

    try:
        for event in api.stream_chat(
            message=text,
            agent_id=agent_id,
            images=image_ids,
            enable_web_search=enable_web_search,
        ):
            events.append(event)
            if event.get("event") != "response.output_text.delta":
                continue
            delta = event.get("data", {}).get("delta", "")
            if delta:
                sent_text.append(delta)
                yield "data: " + json.dumps(_openai_chunk(
                    response_id,
                    created,
                    model_name,
                    delta={"role": "assistant", "content": delta},
                )) + "\n\n"

        output = extract_output_from_events(events)
        output["downloadedImages"] = _run_async(
            download_images_from_output(api, output)
        )
        final_text = output.get("content", {}).get("text", "")
        final_delta = ""
        if not sent_text and final_text:
            final_delta = final_text
        links = [
            item.get("downloadUrl")
            for item in output.get("downloadedImages", [])
            if item.get("downloadUrl")
        ]
        if links:
            final_delta = (
                final_delta + "\n\n" if final_delta else ""
            ) + "\n".join(links)
        finish_reason = (
            "error"
            if output.get("finishedReason") in ("error", "failed")
            else "stop"
        )
        if final_delta:
            yield "data: " + json.dumps(_openai_chunk(
                response_id,
                created,
                model_name,
                delta={"content": final_delta},
                finish_reason=finish_reason,
                usage=_openai_usage(output),
            )) + "\n\n"
        else:
            yield "data: " + json.dumps(_openai_chunk(
                response_id,
                created,
                model_name,
                finish_reason=finish_reason,
                usage=_openai_usage(output),
            )) + "\n\n"
    except Exception as exc:
        yield "data: " + json.dumps(_openai_chunk(
            response_id,
            created,
            model_name,
            delta={"role": "assistant", "content": f"Bridge error: {exc}"},
            finish_reason="error",
        )) + "\n\n"
    yield "data: [DONE]\n\n"


# ── Routes existantes ──────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "authenticated": auth.has_credentials,
        "authMode": auth.mode,
        "modelsCached": len(CACHED_MODELS),
        "quota": {
            "messages": message_limiter.state(),
            "newChats": chat_limiter.state(),
        },
        "timestamp": time.time(),
    })


@app.route("/usage", methods=["GET"])
def usage():
    """Report the quotas the bridge respects and the account's own usage."""
    report = {
        "bridge": {
            "messages": message_limiter.state(),
            "newChats": chat_limiter.state(),
        },
        "models": {
            "parked": model_health.state(),
        },
        "timestamp": time.time(),
    }
    try:
        report["franceStudent"] = _run_async(api.get_user_usage())
    except Exception as exc:
        report["franceStudent"] = {"error": type(exc).__name__}
    try:
        tokens = _run_async(api.get_token_usage())
        report["tokens"] = {
            key: tokens.get(key)
            for key in (
                "promptTokenCount",
                "candidatesTokenCount",
                "totalTokenCount",
                "reasoningTokenCount",
            )
        }
    except Exception as exc:
        report["tokens"] = {"error": type(exc).__name__}
    return jsonify(report)


@app.route("/status", methods=["GET"])
def status():
    """Report the public France Student status page."""
    return jsonify(fetch_status())


@app.route("/v1/refresh", methods=["POST", "GET"])
def refresh_models():
    """Force a live catalogue refresh and return it."""
    try:
        models = _refresh_models(force=True)
    except Exception as exc:
        return jsonify({
            "error": {
                "message": "Impossible de rafraîchir le catalogue France Student.",
                "type": "upstream_error",
                "code": "model_catalog_refresh_failed",
                "detail": type(exc).__name__,
            }
        }), 503
    return jsonify({
        "object": "list",
        "count": len(models),
        "data": [openai_model_entry(model) for model in models],
    })


@app.route("/auth/status", methods=["GET"])
def auth_status():
    return jsonify({
        "authenticated": auth.has_credentials,
        "authMode": auth.mode,
    })


@app.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    if data.get("email"):
        os.environ["FS_EMAIL"] = data["email"]
    if data.get("password"):
        os.environ["FS_PASSWORD"] = data["password"]
    auth.clear()
    try:
        auth.get_token(force=True)
        return jsonify({"status": "ok", "authenticated": True})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 401


@app.route("/models", methods=["GET"])
def get_models():
    try:
        models = _refresh_models(force=True)
        return jsonify({"models": models, "count": len(models)})
    except Exception as e:
        if CACHED_MODELS:
            return jsonify({"models": CACHED_MODELS, "count": len(CACHED_MODELS), "cached": True})
        return jsonify({"error": str(e)}), 500



@app.route("/v1/models", methods=["GET"])
def openai_models():
    """Endpoint OpenAI-compatible /v1/models."""
    force_refresh = request.args.get("refresh", "").lower() in {"1", "true", "yes"}
    try:
        models = _refresh_models(force=force_refresh)
    except Exception:
        if force_refresh:
            return jsonify({
                "error": {
                    "message": "Impossible de rafraîchir le catalogue France Student.",
                    "type": "upstream_error",
                    "code": "model_catalog_refresh_failed",
                }
            }), 503
        models = CACHED_MODELS
    data = [openai_model_entry(model) for model in models]
    return jsonify({"object": "list", "data": data})

@app.route("/chat/completions", methods=["POST"])
def chat_completions():
    data = request.get_json() or {}
    message = data.get("message") or data.get("prompt") or ""
    if not message:
        return jsonify({"error": "message or prompt required"}), 400

    if isinstance(message, list):
        message = openai_messages_to_text([{"role": "user", "content": message}])
    requested_agent = data.get("agentId") or data.get("model")
    agent_id = _resolve_agent_id(requested_agent)

    images = data.get("images", [])
    files = data.get("files", [])
    enable_web_search = data.get("enableWebSearch", False)
    stream = data.get("stream", True)

    def generate():
        try:
            events = _run_async(api.create_chat(
                message=message,
                agent_id=agent_id,
                images=images,
                files=files,
                enable_web_search=enable_web_search,
            ))
        except Exception as e:
            yield f"data: {json.dumps({'error': {'message': str(e), 'code': 'upstream_request_failed'}})}\n\n"
            yield "data: [DONE]\n\n"
            return

        output = extract_output_from_events(events)
        if not output.get("isFinished"):
            last_id = None
            for ev in events:
                if ev.get("last_event_id"):
                    last_id = ev["last_event_id"]
            if last_id:
                chat_id = output.get("chatId")
                for attempt in range(MAX_RETRIES):
                    try:
                        reconnect_events = _run_async(api.reconnect_stream(chat_id, last_id))
                        events.extend(reconnect_events)
                        output = extract_output_from_events(events)
                        break
                    except Exception:
                        if attempt < MAX_RETRIES - 1:
                            time.sleep(RETRY_DELAYS[attempt])
                        else:
                            output["finishedReason"] = "timeout"

        image_results = _run_async(download_images_from_output(api, output))
        output["downloadedImages"] = image_results

        if stream:
            yield f"data: {json.dumps(output)}\n\n"
            yield "data: [DONE]\n\n"
        else:
            yield json.dumps(output)

    if stream:
        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    else:
        raw = "".join(generate())
        if not raw.strip():
            return jsonify({"finishedReason": "error", "errorMessage": "Bridge returned empty response", "content": {"text": ""}})
        try:
            return jsonify(json.loads(raw))
        except Exception:
            return jsonify({"finishedReason": "error", "errorMessage": f"Bridge parse error: {raw[:200]}", "content": {"text": ""}})


# ── NOUVEAU : /v1/chat/completions OpenAI-compatible ───────────────

def _log_request_shape(data, session_id, request_kind, directory):
    """Log the shape of an incoming OpenCode request, never its secrets."""
    import logging
    logger = logging.getLogger("france_student_bridge.request")
    messages = data.get("messages") or []
    summary = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            preview = " ".join(
                str(part.get("text", "")) for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        else:
            preview = str(content or "")
        summary.append({
            "role": message.get("role"),
            "chars": len(preview),
            "head": preview[:160].replace("\n", " "),
        })
    tools = []
    for tool in (data.get("tools") or []):
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") or {}
        parameters = function.get("parameters") or {}
        tools.append({
            "name": function.get("name"),
            "required": parameters.get("required") or [],
            "properties": sorted((parameters.get("properties") or {}).keys()),
        })
    logger.info(
        "request_shape kind=%s session=%s directory=%s model=%s tools=%s messages=%s",
        request_kind, short_session(session_id), bool(directory),
        data.get("model"), tools, json.dumps(summary, ensure_ascii=False),
    )
    dump = os.environ.get("FS_DEBUG_REQUEST_DUMP")
    if dump:
        # Writes the last request to a file so the tool schemas and the
        # agent instructions can be inspected locally.
        from pathlib import Path as _Path
        _Path(dump).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )


def short_session(session_id):
    if not session_id:
        return "-"
    import hashlib
    return hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()[:8]


@app.route("/v1/chat/completions", methods=["POST"])
def openai_chat_completions():
    """OpenAI-compatible interface with one durable FS chat per OpenCode session."""
    data = request.get_json(silent=True) or {}
    session_id = (
        request.headers.get("X-OpenCode-Session-ID")
        or request.headers.get("X-OpenCode-Session")
    )
    request_kind = request.headers.get("X-OpenCode-Request-Kind", "primary")
    directory = request.headers.get("X-OpenCode-Directory")
    agent = request.headers.get("X-OpenCode-Agent")
    if os.environ.get("FS_DEBUG_REQUEST"):
        _log_request_shape(data, session_id, request_kind, directory)

    # Some OpenCode agents are deterministic commands. The bridge runs them
    # itself: no model, no France Student message.
    if agent and agent.strip().lower() == FS_ACTION_AGENT.strip().lower():
        report = report_refresh(f"http://{SERVER_HOST}:{SERVER_PORT}")
        completion = openai_response_to_sse(
            {
                "content": {"text": report},
                "finishedReason": "completed",
                "model": data.get("model") or "",
            },
            data.get("model") or "",
            delta_mode=bool(data.get("stream", False)),
        )
        completion["bridge_action"] = agent
        if data.get("stream", False):
            payload = json.dumps(completion, ensure_ascii=False)
            return Response(
                f"data: {payload}\n\ndata: [DONE]\n\n",
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return jsonify(completion)

    # Test agent: sends a simple "$opencodetest" message to France Student
    # and returns the model's answer. Used to verify the bridge is working.
    if agent and agent.strip().lower() == FS_TEST_AGENT.strip().lower():
        report = test_connection(f"http://{SERVER_HOST}:{SERVER_PORT}")
        completion = openai_response_to_sse(
            {
                "content": {"text": report},
                "finishedReason": "completed",
                "model": data.get("model") or "",
            },
            data.get("model") or "",
            delta_mode=bool(data.get("stream", False)),
        )
        completion["bridge_action"] = agent
        if data.get("stream", False):
            payload = json.dumps(completion, ensure_ascii=False)
            return Response(
                f"data: {payload}\n\ndata: [DONE]\n\n",
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return jsonify(completion)

    try:
        completion = agentic_bridge.complete(
            data,
            session_id,
            request_kind=request_kind,
            directory=directory,
        )
    except BridgeError as exc:
        return jsonify(exc.response()), exc.status

    if data.get("stream", False):
        payload = json.dumps(completion, ensure_ascii=False)
        return Response(
            f"data: {payload}\n\ndata: [DONE]\n\n",
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    return jsonify(completion)


@app.route("/v1/images/generations", methods=["POST"])
def openai_image_generations():
    """Generate images by delegating to France Student's image-generation tool."""
    data = request.get_json() or {}
    prompt = data.get("prompt", "")
    if not isinstance(prompt, str) or not prompt.strip():
        return jsonify({
            "error": {
                "message": "prompt is required",
                "type": "invalid_request_error",
                "param": "prompt",
            }
        }), 400

    try:
        count = int(data.get("n", 1))
    except (TypeError, ValueError):
        count = 1
    if count < 1 or count > 8:
        return jsonify({
            "error": {
                "message": "n must be between 1 and 8",
                "type": "invalid_request_error",
                "param": "n",
            }
        }), 400

    requested_model = data.get("model", DEFAULT_IMAGE_MODEL)
    canonical = canonical_model_name(requested_model)
    if isinstance(canonical, str) and canonical.lower() == DEFAULT_IMAGE_MODEL.lower():
        agent_id = (
            _resolve_agent_id(DEFAULT_IMAGE_MODEL, strict=True)
            or DEFAULT_IMAGE_AGENT_ID
        )
    else:
        agent_id = DEFAULT_IMAGE_AGENT_ID

    response_format = data.get("response_format", "url")
    if response_format not in ("url", "b64_json"):
        return jsonify({
            "error": {
                "message": "response_format must be url or b64_json",
                "type": "invalid_request_error",
                "param": "response_format",
            }
        }), 400

    generated = []
    errors = []
    generation_prompt = _image_generation_prompt(
        prompt.strip(),
        size=data.get("size"),
        quality=data.get("quality"),
    )
    for index in range(count):
        chat_id = None
        try:
            events = _run_async(api.create_chat(
                message=generation_prompt,
                agent_id=agent_id,
            ))
            output = extract_output_from_events(events)
            chat_id = output.get("chatId")
            if output.get("finishedReason") != "completed":
                raise RuntimeError(
                    output.get("errorMessage") or "Image generation did not complete"
                )
            output["downloadedImages"] = _run_async(
                download_images_from_output(api, output)
            )
            successful = [
                item for item in output["downloadedImages"]
                if item.get("localPath") and item.get("filename")
            ]
            if not successful:
                raise RuntimeError("France Student returned no downloadable image")

            image = successful[0]
            revised_prompt = prompt
            for item in reversed(output.get("imageItems", [])):
                if item.get("revisedPrompt"):
                    revised_prompt = item["revisedPrompt"]
                    break
            if response_format == "b64_json":
                encoded = base64.b64encode(
                    Path(image["localPath"]).read_bytes()
                ).decode("ascii")
                generated.append({
                    "b64_json": encoded,
                    "revised_prompt": revised_prompt,
                })
            else:
                generated.append({
                    "url": image["downloadUrl"],
                    "revised_prompt": revised_prompt,
                })
        except Exception as exc:
            errors.append({"index": index, "message": str(exc)})
        finally:
            if chat_id:
                try:
                    _run_async(api.delete_chat(chat_id))
                except Exception:
                    pass

    if not generated:
        return jsonify({
            "error": {
                "message": errors[0]["message"] if errors else "Image generation failed",
                "type": "image_generation_error",
                "code": "upstream_error",
            },
            "errors": errors,
        }), 502

    response = {
        "created": int(time.time()),
        "data": generated,
    }
    if errors:
        response["errors"] = errors
    return jsonify(response)


# ── Routes existantes suite ────────────────────────────────────────

@app.route("/chat/<chat_id>/message", methods=["POST"])
def send_chat_message(chat_id):
    data = request.get_json() or {}
    message = data.get("message") or data.get("content") or ""
    if not message:
        return jsonify({"error": "message or content required"}), 400

    images = data.get("images", [])
    files = data.get("files", [])
    agent_id = data.get("agentId")
    enable_web_search = data.get("enableWebSearch", False)
    stream = data.get("stream", True)

    def generate():
        try:
            events = _run_async(api.send_message(
                chat_id=chat_id,
                message=message,
                agent_id=agent_id,
                images=images,
                files=files,
                enable_web_search=enable_web_search,
            ))
        except Exception as e:
            yield f"data: {json.dumps({'error': {'message': str(e), 'code': 'upstream_request_failed'}})}\n\n"
            yield "data: [DONE]\n\n"
            return

        output = extract_output_from_events(events)
        if not output.get("isFinished"):
            last_id = None
            for ev in events:
                if ev.get("last_event_id"):
                    last_id = ev["last_event_id"]
            if last_id:
                for attempt in range(MAX_RETRIES):
                    try:
                        reconnect_events = _run_async(api.reconnect_stream(chat_id, last_id))
                        events.extend(reconnect_events)
                        output = extract_output_from_events(events)
                        break
                    except Exception:
                        if attempt < MAX_RETRIES - 1:
                            time.sleep(RETRY_DELAYS[attempt])
                        else:
                            output["finishedReason"] = "timeout"

        image_results = _run_async(download_images_from_output(api, output))
        output["downloadedImages"] = image_results

        if stream:
            yield f"data: {json.dumps(output)}\n\n"
            yield "data: [DONE]\n\n"
        else:
            yield json.dumps(output)

    if stream:
        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    else:
        raw = "".join(generate())
        if not raw.strip():
            return jsonify({"finishedReason": "error", "errorMessage": "Bridge returned empty response", "content": {"text": ""}})
        try:
            return jsonify(json.loads(raw))
        except Exception:
            return jsonify({"finishedReason": "error", "errorMessage": f"Bridge parse error: {raw[:200]}", "content": {"text": ""}})


@app.route("/chat/<chat_id>", methods=["GET"])
def get_chat_detail(chat_id):
    try:
        result = _run_async(api.get_chat(chat_id))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chat/<chat_id>/delete", methods=["DELETE"])
def delete_chat(chat_id):
    try:
        _run_async(api.delete_chat(chat_id))
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chats", methods=["GET"])
def list_chats():
    limit = request.args.get("limit", 20, type=int)
    cursor = request.args.get("cursor")
    try:
        result = _run_async(api.get_chats(limit=limit, cursor_chat_id=cursor))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chat/<chat_id>/usage", methods=["GET"])
def chat_usage(chat_id):
    try:
        result = _run_async(api.get_chat_usage(chat_id))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/images/<filename>", methods=["GET"])
def serve_image(filename):
    safe_name = Path(filename).name
    filepath = IMAGES_DIR / safe_name
    if not filepath.exists():
        return jsonify({"error": "image not found"}), 404
    return send_file(str(filepath))


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "file required"}), 400
    f = request.files["file"]
    content = f.read()
    if len(content) > MAX_UPLOAD_BYTES:
        return jsonify({"error": "file exceeds MAX_UPLOAD_BYTES"}), 413
    filename = Path(f.filename or "upload.bin").name
    content_type = f.mimetype or "application/octet-stream"
    try:
        result = _run_async(api.upload_bytes(filename, content, content_type))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def main():
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print(f">>> Bridge Service démarré sur http://{SERVER_HOST}:{SERVER_PORT}")
    print(f"   Health: http://{SERVER_HOST}:{SERVER_PORT}/health")
    print(f"   Models: http://{SERVER_HOST}:{SERVER_PORT}/models")
    print(f"   OpenAI: http://{SERVER_HOST}:{SERVER_PORT}/v1/chat/completions")
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()

