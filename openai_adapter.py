import time

"""
Adaptateur OpenAI /v1/chat/completions -> format bridge France Student.
"""

import json
import uuid

from tool_loop import parse_function_call, has_function_call


def extract_openai_images(messages):
    """Return image_url references from OpenAI multimodal messages."""
    images = []
    for message in messages:
        content = message.get("content", "")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            image_url = part.get("image_url", "")
            if isinstance(image_url, dict):
                image_url = image_url.get("url", "")
            if image_url:
                images.append(image_url)
    return images


def openai_messages_to_text(messages):
    """Convertit un tableau de messages OpenAI en texte pour France Student."""
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                else:
                    text_parts.append(str(part))
            content = "\n".join(text_parts)

        if role == "system":
            parts.append(f"[INSTRUCTIONS SYSTÈME]\n{content}")
        elif role == "user":
            parts.append(content)
        elif role == "assistant":
            if content:
                parts.append(f"[Assistant]: {content}")
            tool_calls = msg.get("tool_calls", [])
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                args = func.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        pass
                parts.append(
                    f'<function_call>\n{{"name": "{name}", "arguments": {json.dumps(args, ensure_ascii=False)}}}\n</function_call>'
                )
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", "unknown")
            parts.append(f"[RÉSULTAT DE L'OUTIL {tool_call_id}]\n{content}")

    return "\n\n".join(parts)


def openai_response_to_sse(output, model_name="gpt-5.6-sol", delta_mode=False):
    """Convertit la sortie bridge en format OpenAI Chat Completion."""
    content = output.get("content", {})
    text = content.get("text", "")
    function_calls = content.get("functionCalls", [])
    finish_reason = output.get("finishedReason", "stop")
    token_usage = output.get("tokenUsage", {})

    reason_map = {
        "completed": "stop",
        "timeout": "length",
        "failed": "error",
        "error": "error",
        None: "stop",
    }
    openai_reason = reason_map.get(finish_reason, "stop")

    # Parser le function_call (format natif ou forcé)
    fc = parse_function_call(text)
    if fc and not function_calls:
        function_calls = [{"name": fc.get("name", ""), "arguments": json.dumps(fc.get("arguments", {}), ensure_ascii=False)}]
    elif not fc and has_function_call(text):
        fc = parse_function_call(text)
        if fc:
            function_calls = [{"name": fc.get("name", ""), "arguments": json.dumps(fc.get("arguments", {}), ensure_ascii=False)}]

    has_tool_calls = bool(function_calls)
    if not has_tool_calls:
        links = [
            item.get("downloadUrl")
            for item in output.get("downloadedImages", [])
            if item.get("downloadUrl")
        ]
        if links:
            text = (text + "\n\n" if text else "") + "\n".join(links)

    choice = {
        "index": 0,
        "finish_reason": "tool_calls" if has_tool_calls else openai_reason,
    }

    content_key = "delta" if delta_mode else "message"

    if has_tool_calls:
        tool_calls_list = []
        for i, f in enumerate(function_calls):
            # A call may arrive in the OpenAI shape ({"function": {...}}) or in
            # the flat shape used by the France Student stream items.
            nested = f.get("function") if isinstance(f, dict) else None
            source = nested if isinstance(nested, dict) else f
            name = source.get("name", "")
            if isinstance(name, dict):
                name = name.get("name", "")
            arguments = source.get("arguments", "{}")
            if isinstance(arguments, dict):
                arguments = json.dumps(arguments, ensure_ascii=False)
            # France Student identifies a client tool call with its own
            # call_id. Keeping it as the OpenAI tool call id lets the result
            # be correlated with the pending call.
            call_id = (
                f.get("id") or f.get("call_id") or f"call_{uuid.uuid4().hex[:12]}"
            )
            tool_calls_list.append({
                "id": str(call_id),
                "type": "function",
                "function": {
                    "name": str(name),
                    "arguments": str(arguments),
                }
            })
        choice[content_key] = {
            "role": "assistant",
            "content": None,
            "tool_calls": tool_calls_list,
        }
    else:
        choice[content_key] = {
            "role": "assistant",
            "content": text,
        }

    input_tokens = (token_usage or {}).get("input_tokens") or (token_usage or {}).get("promptTokenCount", 0)
    output_tokens = (token_usage or {}).get("output_tokens") or (token_usage or {}).get("candidatesTokenCount", 0)
    total_tokens = (token_usage or {}).get("total_tokens") or (token_usage or {}).get("totalTokenCount", 0)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk" if delta_mode else "chat.completion",
        "created": int(time.time()),
        "model": output.get("model") or model_name,
        "choices": [choice],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": total_tokens,
        },
    }
