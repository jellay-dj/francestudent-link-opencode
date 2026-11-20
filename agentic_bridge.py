"""OpenCode-aware request handling over persistent France Student chats."""

import asyncio
import json
import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx

from api_client import FranceStudentLimitError, IncompleteSSEStream
from config.config import (
    FORWARD_SYSTEM_PROMPT,
    FS_CHAT_TOTAL_TIMEOUT,
    FS_FALLBACK_MODELS,
    FS_MAX_MESSAGES_PER_HOUR,
    FS_MAX_NEW_CHATS_PER_DAY,
    FS_MODEL_BLOCK_SECONDS,
    FS_PROJECT_ID,
    FS_QUOTA_WAIT_TIMEOUT,
    FS_REUSE_LAST_CHAT,
    MAX_INITIAL_CONTEXT_CHARS,
    MAX_TOOL_REPAIR_ROUNDS,
    MAX_TOOL_RESULT_CHARS,
    REQUIRE_OPENCODE_SESSION,
)
from image_handler import download_images_from_output, upload_openai_image
from model_catalog import resolve_agent
from model_health import ModelHealth
from openai_adapter import extract_openai_images, openai_response_to_sse
from rate_limiter import SlidingWindowLimiter
from session_store import fingerprint, session_store, short_id
from sse_parser import extract_output_from_events
from tool_bridge import (
    build_tool_plan,
    parse_arguments,
    translate_call,
    translate_arguments,
)
from tool_loop import (
    parse_function_call,
    validate_arguments,
    validate_function_calls,
)


logger = logging.getLogger("france_student_bridge.agentic")

# Quota guards. Every outbound France Student message passes through the
# hourly limiter, and every new conversation through the daily one. The
# defaults stay below the published France Student limits.
message_limiter = SlidingWindowLimiter(FS_MAX_MESSAGES_PER_HOUR, 3600.0)
chat_limiter = SlidingWindowLimiter(FS_MAX_NEW_CHATS_PER_DAY, 86400.0)

# Models France Student currently refuses (quota reached for that model).
model_health = ModelHealth(FS_MODEL_BLOCK_SECONDS)

_SAFE_AUTH_DIAGNOSTIC = re.compile(r"^[A-Za-z0-9_.=, -]{1,240}$")


def _catalog_failure_detail(exc):
    """Expose only the categorical auth summary, never exception payloads."""
    message = str(exc)
    marker = "Diagnostic sans secrets :"
    if marker in message:
        detail = message.split(marker, 1)[1].strip()
        if _SAFE_AUTH_DIAGNOSTIC.fullmatch(detail):
            return detail
    return type(exc).__name__


class BridgeError(Exception):
    def __init__(self, message, *, status=502, code="upstream_error", error_type="upstream_error", ambiguous=False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.error_type = error_type
        self.ambiguous = ambiguous

    def response(self):
        return {
            "error": {
                "message": str(self),
                "type": self.error_type,
                "code": self.code,
            }
        }


def _run_async(coro):
    async def bounded():
        return await asyncio.wait_for(coro, timeout=FS_CHAT_TOTAL_TIMEOUT)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(bounded())
    if not loop.is_running():
        return loop.run_until_complete(bounded())
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, bounded()).result(timeout=FS_CHAT_TOTAL_TIMEOUT + 5)


def _content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif item.get("type") in ("image_url", "input_image"):
                    continue
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(parts)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return "" if content is None else str(content)


def _message_hash(message):
    return fingerprint({
        "role": message.get("role"),
        "content": message.get("content"),
        "name": message.get("name"),
        "metadata": message.get("metadata"),
    })


def _call_id(message):
    return message.get("tool_call_id") or message.get("toolCallId")


def _tool_names_by_id(messages, pending):
    result = dict(pending or {})
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls", []) or []:
            call_id = call.get("id")
            function = call.get("function", {})
            name = function.get("name") if isinstance(function, dict) else None
            if call_id and name:
                result[call_id] = name
    return result


def _tool_result_status(message, text, tool_name):
    explicit_status = message.get("status")
    if isinstance(explicit_status, str):
        normalized = explicit_status.lower().replace("-", "_").replace(" ", "_")
        if normalized in {
            "success", "succeeded", "completed", "error", "failed",
            "permission_denied", "refused", "interrupted", "cancelled",
            "canceled", "timeout", "timed_out", "user_information",
        }:
            return {
                "succeeded": "success",
                "completed": "success",
                "failed": "error",
                "refused": "permission_refused",
                "cancelled": "interrupted",
                "canceled": "interrupted",
                "timed_out": "timeout",
            }.get(normalized, normalized)
    if message.get("is_error") is True or message.get("isError") is True:
        return "error"
    lowered = text.strip().lower()
    if re.search(r"\b(permission|approval)\b.{0,40}\b(denied|rejected|refused)\b|\b(user declined|user rejected)\b", lowered):
        return "permission_refused"
    if re.search(r"\b(interrupted|cancelled|canceled|aborted)\b", lowered):
        return "interrupted"
    if re.search(r"\b(timed? out|timeout)\b", lowered):
        return "timeout"
    if re.search(r"\b(exit code|exit status)\s*[:=]?\s*0\b", lowered):
        return "success"
    if re.search(r"\b(exit code|exit status)\s*[:=]?\s*-?[1-9][0-9]*\b", lowered):
        return "error"
    if re.match(r"^(error|failed|exception)\s*[:(]", lowered):
        return "error"
    if tool_name in ("question", "ask_user"):
        return "user_information"
    return "result_received"


def _format_tool_result(message, tool_id, tool_name):
    text = _content_text(message.get("content"))
    status = _tool_result_status(message, text, tool_name)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "\n[tronqué]"
    name = tool_name or message.get("name") or "outil"
    return f"[{name} → {status}]\n{text or '[vide]'}"


def _tool_result_payloads(activities, tool_names):
    """Build the France Student ``toolResults`` entries for tool activities."""
    payloads = []
    for _index, kind, message, tool_id in activities:
        if kind != "tool":
            continue
        text = _content_text(message.get("content"))
        status = _tool_result_status(message, text, tool_names.get(tool_id))
        if len(text) > MAX_TOOL_RESULT_CHARS:
            text = text[:MAX_TOOL_RESULT_CHARS] + "\n[tronqué]"
        payloads.append({
            "callId": tool_id,
            "output": text or "[vide]",
            "isError": status in {
                "error", "permission_refused", "timeout", "interrupted"
            },
        })
    return payloads


def _render_history(messages, tool_names):
    """Render the OpenCode conversation as a plain, flat transcript.

    The transcript is deliberately flat and unlabelled. The France Student
    models refuse to act when the conversation is dressed up as another
    agent's harness, so the transcript keeps the shape of a normal chat.
    """
    blocks = []
    for message in messages:
        role = message.get("role", "user")
        text = _content_text(message.get("content"))
        if role in ("system", "developer"):
            if text and FORWARD_SYSTEM_PROMPT:
                blocks.append(text)
        elif role == "user":
            if text:
                blocks.append(text)
        elif role == "assistant":
            if text:
                blocks.append(text)
        elif role == "tool":
            call_id = _call_id(message) or "unknown"
            blocks.append(_format_tool_result(message, call_id, tool_names.get(call_id)))
    return "\n\n".join(blocks)


def _truncate_context(text):
    if len(text) <= MAX_INITIAL_CONTEXT_CHARS:
        return text
    head = MAX_INITIAL_CONTEXT_CHARS * 2 // 3
    tail = MAX_INITIAL_CONTEXT_CHARS - head
    return text[:head] + "\n[contexte tronqué]\n" + text[-tail:]


def _initial_content(messages, tools, directory, *, recovered=False):
    # Ne garder que les derniers messages pour limiter la taille du contexte
    # envoye a chaque tour. Le contexte precedent reste disponible sur demande
    # via les outils de lecture de fichiers.
    keep = 5
    recent = messages[-keep:] if len(messages) > keep else messages

    parts = []
    for message in recent:
        role = message.get("role", "user")
        text = _content_text(message.get("content"))
        if not text:
            continue
        if role in ("system", "developer"):
            if FORWARD_SYSTEM_PROMPT:
                parts.append(text)
        elif role == "user":
            parts.append(text)
        elif role == "assistant":
            parts.append(text)
        elif role == "tool":
            call_id = _call_id(message) or "unknown"
            parts.append(_format_tool_result(message, call_id, None))
    if not parts:
        raise BridgeError(
            "La requête OpenCode ne contient pas de message utilisateur exploitable.",
            status=400,
            code="missing_user_message",
            error_type="invalid_request_error",
        )
    if directory:
        parts.append(f"WD: {directory}")
    if recovered:
        parts.append("(Reprise de conversation après perte de session.)")
    parts.append("Contexte precedent disponible sur demande (outils de lecture de fichiers).")
    return _truncate_context("\n\n".join(parts))


def _new_activities(messages, row):
    user_messages = [(index, message) for index, message in enumerate(messages) if message.get("role") == "user"]
    seen_count = row["seen_user_count"] if row else 0
    seen_ids = set(row["seen_tool_results"] if row else [])
    activities = []
    current_count = len(user_messages)

    if row is None:
        return [], current_count, _message_hash(user_messages[-1][1]) if user_messages else None

    if current_count > seen_count:
        new_users = user_messages[seen_count:]
    elif user_messages and _message_hash(user_messages[-1][1]) != row.get("last_user_hash"):
        # OpenCode may compact a resumed transcript. Rebase its shorter list and
        # forward only the latest user item; FS already has the older history.
        new_users = [user_messages[-1]]
        current_count = len(user_messages)
    else:
        new_users = []

    for ordinal, (index, message) in enumerate(user_messages):
        if (index, message) in new_users:
            activities.append((index, "user", message, None))

    tool_names = _tool_names_by_id(messages, row.get("pending_tool_calls", {}))
    newly_seen_ids = []
    for index, message in enumerate(messages):
        if message.get("role") != "tool":
            continue
        tool_id = _call_id(message)
        if not tool_id:
            raise BridgeError(
                "OpenCode a transmis un résultat d'outil sans tool_call_id; il ne sera pas envoyé au modèle pour éviter une association hasardeuse.",
                status=400,
                code="tool_result_missing_id",
                error_type="invalid_request_error",
            )
        if tool_id in seen_ids:
            continue
        activities.append((index, "tool", message, tool_id))
        newly_seen_ids.append(tool_id)

    activities.sort(key=lambda item: item[0])
    last_hash = _message_hash(user_messages[-1][1]) if user_messages else row.get("last_user_hash")
    return activities, current_count, last_hash, tool_names, newly_seen_ids


def _activity_text(activities, tool_names):
    blocks = []
    for _index, kind, message, tool_id in activities:
        if kind == "user":
            content = _content_text(message.get("content"))
            if content:
                blocks.append(content)
        else:
            blocks.append(_format_tool_result(message, tool_id, tool_names.get(tool_id)))
    return "\n\n".join(blocks)


def _local_title(messages, model_name, stream=False):
    """Build a session title locally.

    OpenCode asks for a title on every new session. Answering it from the
    request itself removes one France Student message per session, which
    matters because France Student meters messages.

    The title follows the pattern ``FS <date_heure> <model>`` so it is
    instantly recognizable in the OpenCode session list.
    """
    date_str = time.strftime("%d/%m/%y %Hh")
    model_short = model_name.split("/")[-1] if "/" in model_name else model_name
    title = f"FS {date_str} {model_short}"
    if len(title) > 60:
        title = title[:60].rstrip()

    choice = {"index": 0, "finish_reason": "stop"}
    if stream:
        choice["delta"] = {"role": "assistant", "content": title}
    else:
        choice["message"] = {"role": "assistant", "content": title}
    return {
        "id": f"chatcmpl-local-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion.chunk" if stream else "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [choice],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "bridge_local_title": True,
    }


def _native_calls(output):
    """Return the France Student native function calls carried by a response."""
    calls = output.get("content", {}).get("functionCalls", []) or []
    normalized = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        name = call.get("name")
        if not isinstance(name, str) or not name:
            continue
        call_id = call.get("call_id") or call.get("id")
        if not call_id:
            continue
        normalized.append({
            "fs_tool": name,
            "call_id": call_id,
            "arguments": parse_arguments(call.get("arguments")),
        })
    return normalized


def _extract_calls(output):
    calls = output.get("content", {}).get("functionCalls", []) or []
    if calls:
        return calls
    parsed = parse_function_call(output.get("content", {}).get("text", ""))
    return [parsed] if parsed else []


def _validate_native_calls(native, tools, client_tools, directory, plan):
    """Turn native France Student calls into validated OpenCode tool calls."""
    declared = {}
    for tool in tools or []:
        function = tool.get("function", tool) if isinstance(tool, dict) else {}
        if isinstance(function, dict) and function.get("name"):
            declared[function["name"]] = function

    normalized = []
    for call in native:
        fs_tool = call["fs_tool"]
        if fs_tool not in client_tools:
            return None, (
                f"France Student a demandé l'outil client {fs_tool!r}, "
                "qui n'a pas été déclaré pour cette requête."
            )
        openai_call = translate_call(
            fs_tool, call["arguments"], call["call_id"], directory, plan
        )
        if openai_call is None:
            return None, (
                f"France Student a demandé l'outil client {fs_tool!r}, "
                "qui n'a pas d'équivalent parmi les outils OpenCode."
            )
        name = openai_call["function"]["name"]
        function = declared.get(name)
        if function is None:
            return None, f"OpenCode n'a pas fourni l'outil {name!r} demandé par le modèle."
        payload = json.loads(openai_call["function"]["arguments"] or "{}")
        error = validate_arguments(payload, function.get("parameters", {}))
        if error:
            return None, f"Appel refusé pour {name}: {error}."
        normalized.append(openai_call)
    return normalized, None


def _tool_validation_repair(output, tools, client_tools, directory, plan=None):
    """Return the OpenCode tool calls of a response, or why they are refused."""
    native = _native_calls(output)
    if native:
        normalized, error = _validate_native_calls(
            native, tools, client_tools, directory, plan
        )
        if error:
            return error
        # Replace the native calls by their OpenCode translation so the
        # OpenAI adapter emits the tool calls OpenCode can execute.
        output.setdefault("content", {})["functionCalls"] = normalized
        return None
    calls = _extract_calls(output)
    if not calls:
        return None
    if not tools:
        return "Le modèle a demandé un outil, mais OpenCode n'en a fourni aucun pour cet appel."
    normalized, error = validate_function_calls(calls, tools)
    if error:
        return error
    output.setdefault("content", {})["functionCalls"] = normalized
    return None


def _upstream_output(api, events, chat_id=None):
    output = extract_output_from_events(events)
    resolved_chat_id = output.get("chatId") or chat_id
    if not output.get("isFinished"):
        last_id = next((event.get("last_event_id") for event in reversed(events) if event.get("last_event_id")), None)
        if resolved_chat_id and last_id:
            try:
                tail = _run_async(api.reconnect_stream(resolved_chat_id, last_id))
                events = list(events) + list(tail)
                output = extract_output_from_events(events)
                resolved_chat_id = output.get("chatId") or resolved_chat_id
            except Exception as exc:
                raise BridgeError(
                    f"Le flux France Student a été interrompu et la reprise a échoué ({type(exc).__name__}). Aucun nouvel envoi automatique n'a été fait.",
                    status=504,
                    code="upstream_stream_interrupted",
                    ambiguous=True,
                ) from exc
        else:
            raise BridgeError(
                "France Student a fermé le flux sans confirmation terminale. Aucun nouvel envoi automatique n'a été fait.",
                status=504,
                code="upstream_incomplete",
                ambiguous=True,
            )
    if output.get("finishedReason") != "completed":
        reason = output.get("finishedReason") or "unknown"
        detail = output.get("errorMessage") or reason
        raise BridgeError(
            f"France Student n'a pas terminé la réponse ({detail}).",
            status=502,
            code="upstream_" + re.sub(r"[^a-z0-9_]+", "_", str(reason).lower()),
        )
    if not resolved_chat_id:
        raise BridgeError(
            "France Student a terminé sans fournir d'identifiant de chat; l'association de session ne peut pas être garantie.",
            status=502,
            code="upstream_missing_chat_id",
        )
    output["chatId"] = resolved_chat_id
    try:
        output["downloadedImages"] = _run_async(download_images_from_output(api, output))
    except Exception:
        output["downloadedImages"] = []
        logger.warning("image_download_failed chat=%s", short_id(resolved_chat_id))
    return output


class AgenticBridge:
    def __init__(self, api, models_provider, store=session_store):
        self.api = api
        self.models_provider = models_provider
        self.store = store

    def _reserve_quota(self, creating_chat):
        """Wait for a free France Student slot before sending anything."""
        if not message_limiter.acquire(timeout=FS_QUOTA_WAIT_TIMEOUT):
            raise BridgeError(
                "Le quota horaire de messages France Student est atteint côté "
                "bridge. Réessaie dans quelques minutes.",
                status=429, code="bridge_quota_exhausted",
                error_type="rate_limit_error",
            )
        if creating_chat and not chat_limiter.acquire(timeout=FS_QUOTA_WAIT_TIMEOUT):
            raise BridgeError(
                "Le quota quotidien de conversations France Student est atteint "
                "côté bridge. Réessaie demain.",
                status=429, code="bridge_quota_exhausted",
                error_type="rate_limit_error",
            )

    def _reuse_last_chat(self):
        """Find a conversation to continue when a new one is refused."""
        if not FS_REUSE_LAST_CHAT:
            return None
        try:
            row = self.store.latest_chat()
        except Exception:
            return None
        if not row or not row.get("fs_chat_id"):
            return None
        logger.warning(
            "reusing_last_chat fs_chat=%s from_session=%s",
            short_id(row["fs_chat_id"]), short_id(row.get("session_id")),
        )
        return row["fs_chat_id"]

    def _send(self, chat_id, message, agent_id, images, enable_web_search,
              client_tools=None, tool_results=None):
        try:
            if chat_id is None:
                self._reserve_quota(creating_chat=True)
                try:
                    events = _run_async(self.api.create_chat(
                        message=message,
                        agent_id=agent_id,
                        images=images,
                        files=[],
                        enable_web_search=enable_web_search,
                        client_tools=client_tools,
                        project_id=FS_PROJECT_ID or None,
                    ))
                except FranceStudentLimitError:
                    # France Student refused to open a conversation. When the
                    # daily limit is the reason, the bridge continues the
                    # most recent conversation instead of failing.
                    reused = self._reuse_last_chat()
                    if reused is None:
                        raise
                    chat_id = reused
                    events = _run_async(self.api.send_message(
                        chat_id=chat_id,
                        message=message,
                        agent_id=agent_id,
                        images=images,
                        files=[],
                        enable_web_search=enable_web_search,
                        tool_results=tool_results,
                        client_tools=client_tools,
                    ))
            else:
                self._reserve_quota(creating_chat=False)
                events = _run_async(self.api.send_message(
                    chat_id=chat_id,
                    message=message,
                    agent_id=agent_id,
                    images=images,
                    files=[],
                    enable_web_search=enable_web_search,
                    tool_results=tool_results,
                    client_tools=client_tools,
                ))
        except IncompleteSSEStream as exc:
            partial = exc.events
            partial_output = extract_output_from_events(partial)
            last_id = next((event.get("last_event_id") for event in reversed(partial) if event.get("last_event_id")), None)
            if not (partial_output.get("chatId") or chat_id) or not last_id:
                raise BridgeError(
                    "Le flux FS s'est interrompu avant que le bridge puisse identifier un point de reprise. La requête ne sera pas renvoyée automatiquement.",
                    status=504, code="upstream_outcome_unknown", ambiguous=True,
                ) from exc
            events = partial
        return _upstream_output(self.api, events, chat_id)

    def complete(self, data, session_id, *, request_kind="primary", directory=None):
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            raise BridgeError(
                "messages must be a non-empty array.", status=400,
                code="messages_required", error_type="invalid_request_error",
            )
        if not all(isinstance(message, dict) for message in messages):
            raise BridgeError(
                "Each messages entry must be an object.", status=400,
                code="invalid_messages", error_type="invalid_request_error",
            )
        # Rejeter les requêtes dont le contenu est vide ou uniquement des
        # espaces : cela éviterait d'envoyer une requête inutile à France
        # Student qui consommerait du quota horaire pour rien.
        for message in messages:
            if message.get("role") == "user":
                text = _content_text(message.get("content"))
                if not text or not text.strip():
                    raise BridgeError(
                        "Le message utilisateur est vide. Ajoutez du texte avant d'envoyer.",
                        status=400, code="empty_user_message",
                        error_type="invalid_request_error",
                    )

        model_name = data.get("model", "")
        try:
            models = self.models_provider()
        except Exception as exc:
            raise BridgeError(
                f"Impossible de récupérer le catalogue France Student ({_catalog_failure_detail(exc)}).",
                status=503, code="model_catalog_unavailable",
            ) from exc
        agent_id = resolve_agent(model_name, models)
        if agent_id is None:
            raise BridgeError(
                f"Modèle France Student inconnu ou inactif : {model_name!r}.",
                status=404, code="model_not_found", error_type="invalid_request_error",
            )
        if request_kind == "title":
            # A session title does not need the model: answering it locally
            # saves one France Student message per session.
            return _local_title(messages, model_name, bool(data.get("stream", False)))
        tools = data.get("tools") or []
        if not isinstance(tools, list):
            raise BridgeError(
                "tools must be an array.", status=400,
                code="invalid_tools", error_type="invalid_request_error",
            )
        # France Student declares the tools the client can execute, and the
        # model then calls them natively. Only the tools OpenCode really
        # provides are declared, and the mapping is resolved against the
        # schemas the request carries. No model-specific filtering is
        # applied: every France Student model receives the same set of
        # client tools for a given OpenCode request.
        client_tools, tool_plan = build_tool_plan(tools)
        logger.info(
            "tool_plan model=%s agent_id=%s fs_tools=%s",
            model_name, agent_id, ",".join(client_tools),
        )
        stream = bool(data.get("stream", False))
        enable_web_search = bool(data.get("enableWebSearch", False))
        if request_kind not in ("primary", "title", "compaction", "generate"):
            request_kind = "primary"

        if not session_id:
            if REQUIRE_OPENCODE_SESSION:
                raise BridgeError(
                    "OpenCode n'a transmis aucun identifiant de session. Installez le plugin de session France Student avant d'utiliser le bridge.",
                    status=400, code="opencode_session_required", error_type="invalid_request_error",
                )
            return self._complete_auxiliary(messages, tools, model_name, agent_id, directory, stream)

        if not isinstance(session_id, str) or len(session_id) > 256 or not re.fullmatch(r"[A-Za-z0-9._:-]+", session_id):
            raise BridgeError(
                "L'identifiant de session OpenCode est mal formé.", status=400,
                code="invalid_opencode_session", error_type="invalid_request_error",
            )

        candidates = self._candidates(model_name, models, agent_id)
        last_error = None
        for index, (candidate_model, candidate_agent) in enumerate(candidates):
            try:
                response = self._run_session(
                    data, session_id, request_kind, directory,
                    candidate_model, candidate_agent, messages, tools,
                    client_tools, tool_plan, stream, enable_web_search,
                )
            except BridgeError as exc:
                # Un refus de capacité (502 "no responses upstream has
                # available capacity") ou une limite de rate doivent faire
                # basculer sur le modèle suivant, pas lever immédiatement.
                is_capacity_error = (
                    exc.code in ("upstream_rate_limited", "upstream_request_failed")
                    and exc.status in (429, 502, 503)
                    and any(kw in str(exc).lower() for kw in (
                        "capacity", "unavailable", "overload", "busy",
                        "limite atteinte", "rate limit",
                    ))
                )
                if not is_capacity_error:
                    raise
                last_error = exc
                model_health.block(candidate_model)
                if index == len(candidates) - 1:
                    raise
                logger.warning(
                    "model_refused model=%s next=%s",
                    candidate_model, candidates[index + 1][0],
                )
                continue
            if candidate_model != model_name:
                response["bridge_model_fallback"] = {
                    "requested": model_name,
                    "used": candidate_model,
                }
            return response
        raise last_error

    def _candidates(self, model_name, models, agent_id):
        """Ordered list of models to try, the healthy ones first.

        France Student meters some models separately: one model can be
        refused with "limite atteinte" while the others answer. The refused
        model is parked for a while, and the next candidate takes over.
        """
        candidates = [(model_name, agent_id)]
        for name in FS_FALLBACK_MODELS.split(","):
            name = name.strip()
            if not name or name == model_name:
                continue
            fallback_agent = resolve_agent(name, models)
            if fallback_agent is None:
                continue
            candidates.append((name, fallback_agent))
        healthy = [c for c in candidates if model_health.is_available(c[0])]
        parked = [c for c in candidates if not model_health.is_available(c[0])]
        return healthy + parked

    def _run_session(self, data, session_id, request_kind, directory,
                     model_name, agent_id, messages, tools, client_tools,
                     tool_plan, stream, enable_web_search):
        request_hash = fingerprint({
            "model": model_name,
            "messages": messages,
            "tools": tools,
            "enableWebSearch": enable_web_search,
            "request_kind": request_kind,
            "stream": stream,
        })
        tools_hash = fingerprint(tools)
        session_log_id = short_id(session_id)

        with self.store.lock(session_id):
            row = self.store.get(session_id)
            if row and row.get("last_request_hash") == request_hash:
                if row.get("last_request_state") == "completed" and row.get("last_response"):
                    # Déduplication exacte : même requête (même hash) déjà
                    # traitée avec succès. On rejoue la réponse stockée pour
                    # éviter un doublon côté France Student.
                    logger.info("request_replayed session=%s request=%s", session_log_id, request_hash[:12])
                    return row["last_response"]
                if row.get("last_request_state") == "failed":
                    raise BridgeError(
                        "France Student a renvoyé une erreur connue pour cette requête. Le bridge ne la relance pas automatiquement; envoyez un nouveau message pour reprendre.",
                        status=502, code="previous_request_failed",
                    )
                raise BridgeError(
                    "Le résultat du dernier échange FS est incertain. Le bridge ne renvoie pas la même requête mutante afin d'éviter un doublon; ouvrez une nouvelle session OpenCode ou vérifiez le chat France Student associé.",
                    status=409, code="upstream_outcome_unknown",
                )
            if row and row.get("last_request_state") in ("inflight", "ambiguous"):
                raise BridgeError(
                    "La session FS précédente a été interrompue avec un résultat incertain. Aucune nouvelle action n'a été envoyée.",
                    status=409, code="session_recovery_required",
                )

            user_messages = [message for message in messages if message.get("role") == "user"]
            if not user_messages:
                raise BridgeError(
                    "La requête OpenCode ne contient aucun message utilisateur.", status=400,
                    code="missing_user_message", error_type="invalid_request_error",
                )
            recovered = row is None and (
                len(user_messages) > 1
                or any(message.get("role") == "tool" for message in messages)
                or any(message.get("role") == "assistant" for message in messages)
            )
            creating_fs_chat = row is None or not row.get("fs_chat_id")

            if creating_fs_chat:
                activities = []
                seen_user_count = len(user_messages)
                last_user_hash = _message_hash(user_messages[-1])
                seen_tool_ids = [
                    _call_id(message) for message in messages
                    if message.get("role") == "tool" and _call_id(message)
                ]
                pending_tool_calls = {}
                tool_names = _tool_names_by_id(messages, pending_tool_calls)
                tool_results = []
                initial = _initial_content(
                    messages,
                    tools,
                    directory,
                    recovered=recovered or (row is not None),
                )
                image_messages = user_messages
            else:
                activity_result = _new_activities(messages, row)
                activities, seen_user_count, last_user_hash, tool_names, new_tool_ids = activity_result
                tools_changed = tools_hash != row.get("tools_hash")
                if not activities and not tools_changed:
                    raise BridgeError(
                        "La requête ne contient ni nouveau message utilisateur ni nouveau résultat d'outil. Aucune action n'a été répétée.",
                        status=409, code="no_new_session_activity",
                    )
                user_activities = [item for item in activities if item[1] == "user"]
                tool_activities = [item for item in activities if item[1] == "tool"]
                initial = _activity_text(user_activities, tool_names)
                tool_results = _tool_result_payloads(tool_activities, tool_names)
                if tools_changed:
                    initial = "\n\n".join(part for part in (initial,) if part)
                pending_tool_calls = dict(row.get("pending_tool_calls") or {})
                for tool_id in new_tool_ids:
                    pending_tool_calls.pop(tool_id, None)
                seen_tool_ids = list(set(row.get("seen_tool_results", [])) | set(new_tool_ids))
                image_messages = [message for _index, kind, message, _tool_id in user_activities]
                seen_user_count = max(seen_user_count, row.get("seen_user_count", 0))
                if len(user_messages) < row.get("seen_user_count", 0):
                    seen_user_count = len(user_messages)

            image_urls = extract_openai_images(image_messages)
            # Aussi extraire les images envoyées dans le champ "images" du corps
            # de la requête OpenCode (en plus des parties image_url dans le contenu).
            data_images = data.get("images", []) or []
            for img in data_images:
                if isinstance(img, str):
                    image_urls.append(img)
                elif isinstance(img, dict):
                    url = img.get("url", "")
                    if url:
                        image_urls.append(url)
            # Dédupliquer
            image_urls = list(dict.fromkeys(image_urls))
            self.store.mark_inflight(session_id, request_hash, agent_id, model_name)
            try:
                image_uploads = _run_async(self._upload_images(image_urls))
            except Exception as exc:
                self.store.mark_failed(session_id)
                raise BridgeError(
                    f"L'image jointe n'a pas pu être transmise à France Student ({type(exc).__name__}).",
                    status=400, code="image_upload_failed", error_type="invalid_request_error",
                ) from exc
            image_ids = [item["uuid"] for item in image_uploads]

            chat_id = row.get("fs_chat_id") if row and row.get("fs_chat_id") else None
            try:
                output = self._send(
                    chat_id, initial, agent_id, image_ids, enable_web_search,
                    client_tools=client_tools, tool_results=tool_results,
                )
                chat_id = output["chatId"]

                repair_round = 0
                validation_error = _tool_validation_repair(
                    output, tools, client_tools, directory, tool_plan
                )
                while validation_error and repair_round < MAX_TOOL_REPAIR_ROUNDS:
                    repair_round += 1
                    correction = (
                        "[RETOUR DE VALIDATION DU BRIDGE — AUCUN OUTIL N'A ÉTÉ EXÉCUTÉ]\n"
                        f"{validation_error}\n"
                        "Corrige ton appel en utilisant un outil et un schéma présents dans la demande initiale, ou réponds directement si l'action n'est pas possible."
                    )
                    output = self._send(
                        chat_id, correction, agent_id, [], enable_web_search,
                        client_tools=client_tools,
                    )
                    chat_id = output["chatId"]
                    validation_error = _tool_validation_repair(
                        output, tools, client_tools, directory, tool_plan
                    )
                if validation_error:
                    output.setdefault("content", {})["functionCalls"] = []
                    output["content"]["text"] = (
                        "Le bridge a refusé l'appel d'outil non valide après "
                        f"{repair_round} correction(s): {validation_error}"
                    )
                response = openai_response_to_sse(output, model_name, delta_mode=stream)
            except Exception as exc:
                logger.warning(
                    "request_failed session=%s error=%s",
                    session_log_id, type(exc).__name__, exc_info=True,
                )
                if isinstance(exc, BridgeError):
                    self.store.mark_ambiguous(session_id) if exc.ambiguous else self.store.mark_failed(session_id)
                    raise
                if isinstance(exc, FranceStudentLimitError):
                    # The request was refused before any side effect, so the
                    # outcome is known: nothing was sent.
                    self.store.mark_failed(session_id)
                    raise BridgeError(
                        f"France Student a refusé la requête : {exc}",
                        status=429, code="upstream_rate_limited",
                        error_type="rate_limit_error",
                    ) from exc
                if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException, TimeoutError)):
                    self.store.mark_ambiguous(session_id)
                    raise BridgeError(
                        "Le délai maximal d'attente de France Student est dépassé. Le bridge n'a pas relancé la requête, car le résultat amont peut être incertain.",
                        status=504, code="upstream_timeout",
                        ambiguous=True,
                    ) from exc
                self.store.mark_ambiguous(session_id)
                raise BridgeError(
                    f"L'échange France Student a échoué ({type(exc).__name__}). Le bridge n'a pas relancé la requête automatiquement.",
                    status=502, code="upstream_request_failed",
                    ambiguous=True,
                ) from exc

            for call in response.get("choices", [{}])[0].get("message", {}).get("tool_calls", []):
                pending_tool_calls[call["id"]] = call["function"]["name"]
            for call in response.get("choices", [{}])[0].get("delta", {}).get("tool_calls", []):
                pending_tool_calls[call["id"]] = call["function"]["name"]

            if recovered:
                response["bridge_session_recovered"] = True
            self.store.mark_completed(
                session_id,
                chat_id=chat_id,
                agent_id=agent_id,
                model_name=model_name,
                tools_hash=tools_hash,
                seen_user_count=seen_user_count,
                last_user_hash=last_user_hash,
                seen_tool_results=seen_tool_ids,
                pending_tool_calls=pending_tool_calls,
                request_hash=request_hash,
                response=response,
            )
            logger.info(
                "request_completed session=%s fs_chat=%s model=%s request=%s tool_calls=%s",
                session_log_id,
                short_id(chat_id),
                model_name,
                request_hash[:12],
                len(response.get("choices", [{}])[0].get("message", {}).get("tool_calls", [])),
            )
            return response

    async def _upload_images(self, image_urls):
        if not image_urls:
            return []
        # Upload images in parallel: each upload is an independent HTTP call,
        # so running them together cuts wall-clock time when several images
        # are attached.
        return await asyncio.gather(
            *(upload_openai_image(self.api, url) for url in image_urls)
        )
