import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path

from agentic_bridge import (
    AgenticBridge,
    BridgeError,
    _catalog_failure_detail,
    _tool_result_status,
)
from api_client import IncompleteSSEStream
from session_store import SessionStore


MODELS = [
    {
        "id": 905,
        "name": "GPT 6 Astra",
        "model": "gpt-6-astra",
        "modelProvider": "openai",
        "isActive": True,
    },
    {
        "id": 906,
        "name": "Fable 5.2",
        "model": "fable-5.2",
        "modelProvider": "openai",
        "isActive": True,
    },
]


def _events(chat_id, response):
    events = [{
        "event": "stream.open",
        "data": {"chat_id": chat_id},
        "last_event_id": "1",
    }]
    if response.get("text"):
        events.append({
            "event": "response.output_text.delta",
            "data": {"delta": response["text"]},
            "last_event_id": "2",
        })
    for index, call in enumerate(response.get("function_calls", [])):
        item_id = f"fc_{index}"
        call_id = call.get("call_id") or f"call_{index}"
        arguments = json.dumps(call.get("arguments", {}))
        events.append({
            "event": "response.output_item.added",
            "data": {
                "item": {
                    "type": "function_call",
                    "id": item_id,
                    "call_id": call_id,
                    "name": call["name"],
                    "arguments": "",
                    "status": "in_progress",
                }
            },
            "last_event_id": "2",
        })
        events.append({
            "event": "response.function_call_arguments.done",
            "data": {"item_id": item_id, "arguments": arguments},
            "last_event_id": "2",
        })
        events.append({
            "event": "response.output_item.done",
            "data": {
                "item": {
                    "type": "function_call",
                    "id": item_id,
                    "call_id": call_id,
                    "name": call["name"],
                    "arguments": arguments,
                    "status": "completed",
                }
            },
            "last_event_id": "2",
        })
    events.append({
        "event": "completed",
        "data": {
            "chat_id": chat_id,
            "message": {
                "id": "msg-final",
                "model": "gpt-6-astra",
                "modelProvider": "openai",
                "parts": [],
                "tokenUsage": {},
            },
        },
        "last_event_id": "3",
    })
    return events


class FakeFSAPI:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.chats = {}
        self.calls = []
        self.client_tools = []
        self.tool_results = []
        self.project_ids = []
        self._counter = 0
        self._lock = threading.Lock()
        self.reconnect_result = None

    def _next_response(self):
        with self._lock:
            if self.responses:
                return self.responses.pop(0)
        return {"text": "Réponse simulée"}

    async def create_chat(self, *, message, agent_id, images, files,
                          enable_web_search, client_tools=None,
                          project_id=None):
        response = self._next_response()
        with self._lock:
            self._counter += 1
            chat_id = f"fs-chat-{self._counter}"
            self.calls.append(("create", chat_id, message, agent_id, images))
            self.client_tools.append(list(client_tools or []))
            self.tool_results.append(None)
            self.project_ids.append(project_id)
        if isinstance(response, Exception):
            raise response
        self.chats[chat_id] = [message]
        return _events(chat_id, response)

    async def send_message(self, *, chat_id, message, agent_id, images, files,
                           enable_web_search, tool_results=None,
                           client_tools=None):
        response = self._next_response()
        with self._lock:
            self.chats[chat_id].append(message)
            self.calls.append(("send", chat_id, message, agent_id, images))
            self.client_tools.append(list(client_tools or []))
            self.tool_results.append(tool_results)
        if isinstance(response, Exception):
            raise response
        return _events(chat_id, response)

    async def reconnect_stream(self, chat_id, last_event_id):
        if self.reconnect_result is None:
            return []
        return _events(chat_id, self.reconnect_result)


READ_TOOL = {
    "type": "function",
    "function": {
        "name": "read",
        "description": "Lire un fichier",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}


class AgenticBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store_path = Path(self.temp.name) / "sessions.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def make_bridge(self, api, store=None):
        return AgenticBridge(api, lambda: MODELS, store or SessionStore(self.store_path))

    @staticmethod
    def request(messages, *, model="gpt-6-astra", tools=None, stream=False):
        return {
            "model": model,
            "messages": messages,
            "tools": tools or [],
            "stream": stream,
        }

    def test_simple_exchange_selects_live_catalog_id(self):
        api = FakeFSAPI([{"text": "Bonjour depuis FS"}])
        bridge = self.make_bridge(api)
        result = bridge.complete(
            self.request([{"role": "user", "content": "Dis bonjour"}]),
            "ses-astra-1",
        )
        self.assertEqual(result["choices"][0]["message"]["content"], "Bonjour depuis FS")
        self.assertEqual(api.calls[0][0], "create")
        self.assertEqual(api.calls[0][3], 905)

    def test_catalog_failure_exposes_only_safe_auth_diagnostic(self):
        detail = _catalog_failure_detail(RuntimeError(
            "Impossible de s'authentifier. Diagnostic sans secrets : "
            "api=HTTP 401, puppeteer=browser_launch_failed, nextauth=HTTP 403"
        ))
        self.assertEqual(
            detail,
            "api=HTTP 401, puppeteer=browser_launch_failed, nextauth=HTTP 403",
        )
        self.assertEqual(
            _catalog_failure_detail(RuntimeError("token=must-not-escape")),
            "RuntimeError",
        )

    def test_each_new_opencode_session_creates_its_own_fs_chat(self):
        api = FakeFSAPI([{"text": "A"}, {"text": "B"}])
        bridge = self.make_bridge(api)
        first = self.request([{"role": "user", "content": "Session A"}])
        second = self.request([{"role": "user", "content": "Session B"}])
        bridge.complete(first, "ses-a")
        bridge.complete(second, "ses-b")
        self.assertEqual([call[0] for call in api.calls], ["create", "create"])
        self.assertNotEqual(api.calls[0][1], api.calls[1][1])

    def test_chats_are_created_inside_the_configured_france_student_project(self):
        api = FakeFSAPI([{"text": "A"}])
        bridge = self.make_bridge(api)
        bridge.complete(
            self.request([{"role": "user", "content": "Session"}]), "ses-projet"
        )
        self.assertTrue(api.project_ids[0])
        self.assertEqual(api.project_ids[0], api.project_ids[0].strip())

    def test_auxiliary_title_is_answered_locally_and_primary_turn_creates_the_chat(self):
        api = FakeFSAPI([{"text": "Réponse principale"}])
        bridge = self.make_bridge(api)
        title = bridge.complete(
            self.request([{"role": "user", "content": "Génère un titre pour : modifie le fichier"}]),
            "ses-title",
            request_kind="title",
        )
        # The title costs no France Student message.
        self.assertEqual(api.calls, [])
        self.assertTrue(title["bridge_local_title"])
        title_text = title["choices"][0]["message"]["content"]
        # Title format: FS DD/MM/YY HHh <model>
        self.assertTrue(title_text.startswith("FS "), f"Title should start with 'FS ', got: {title_text!r}")
        self.assertIn("gpt-6-astra", title_text, f"Title should contain gpt-6-astra, got: {title_text!r}")

        result = bridge.complete(
            self.request([{"role": "user", "content": "Modifie le fichier."}], tools=[READ_TOOL]),
            "ses-title",
        )
        self.assertEqual([call[0] for call in api.calls], ["create"])
        # The available client tools are declared natively on every turn.
        self.assertEqual(api.client_tools[0], ["list_directory", "read_file"])
        self.assertEqual(result["choices"][0]["message"]["content"], "Réponse principale")

    def test_later_user_message_continues_same_fs_chat_and_survives_restart(self):
        api = FakeFSAPI([{"text": "Première réponse"}, {"text": "Deuxième réponse"}])
        bridge = self.make_bridge(api)
        bridge.complete(self.request([{"role": "user", "content": "Un"}]), "ses-reprise")
        resumed_store = SessionStore(self.store_path)
        resumed_bridge = self.make_bridge(api, resumed_store)
        messages = [
            {"role": "user", "content": "Un"},
            {"role": "assistant", "content": "Première réponse"},
            {"role": "user", "content": "Deux"},
        ]
        result = resumed_bridge.complete(self.request(messages), "ses-reprise")
        self.assertEqual(result["choices"][0]["message"]["content"], "Deuxième réponse")
        self.assertEqual([call[0] for call in api.calls], ["create", "send"])
        self.assertEqual(api.calls[0][1], api.calls[1][1])
        self.assertIn("Deux", api.chats[api.calls[0][1]][1])

    def test_tool_call_returns_correlated_id_and_tool_result_goes_back_to_same_chat(self):
        api = FakeFSAPI([
            {"function_calls": [{"name": "read_file", "arguments": {"path": "note.txt"}}]},
            {"text": "Le fichier contient bonjour."},
        ])
        bridge = self.make_bridge(api)
        user = {"role": "user", "content": "Lis note.txt"}
        first = bridge.complete(self.request([user], tools=[READ_TOOL]), "ses-tools")
        tool_call = first["choices"][0]["message"]["tool_calls"][0]
        # The native client tool is translated into the OpenCode tool.
        self.assertEqual(tool_call["function"]["name"], "read")
        self.assertEqual(
            json.loads(tool_call["function"]["arguments"]),
            {"path": "note.txt"},
        )
        self.assertEqual(api.client_tools[0], ["list_directory", "read_file"])

        second_messages = [
            user,
            {"role": "assistant", "content": None, "tool_calls": [tool_call]},
            {"role": "tool", "tool_call_id": tool_call["id"], "content": "bonjour"},
        ]
        second = bridge.complete(self.request(second_messages, tools=[READ_TOOL]), "ses-tools")
        # The result travels back through the native toolResults channel.
        results = api.tool_results[1]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["callId"], tool_call["id"])
        self.assertEqual(results[0]["output"], "bonjour")
        self.assertFalse(results[0]["isError"])
        self.assertEqual(api.calls[1][1], api.calls[0][1])
        self.assertEqual(second["choices"][0]["message"]["content"], "Le fichier contient bonjour.")

    def test_replayed_same_request_returns_cached_response_without_duplicate(self):
        api = FakeFSAPI([{"text": "Une seule exécution"}])
        bridge = self.make_bridge(api)
        request = self.request([{"role": "user", "content": "Réponds"}])
        first = bridge.complete(request, "ses-cache")
        replay = bridge.complete(request, "ses-cache")
        self.assertEqual(first, replay)
        self.assertEqual(len(api.calls), 1)

    def test_parallel_sessions_are_isolated(self):
        api = FakeFSAPI([{"text": "A"}, {"text": "B"}])
        bridge = self.make_bridge(api)
        requests = [
            (self.request([{"role": "user", "content": "A"}]), "ses-par-a"),
            (self.request([{"role": "user", "content": "B"}]), "ses-par-b"),
        ]
        errors = []

        def run(item):
            try:
                return bridge.complete(item[0], item[1])
            except Exception as exc:  # surfaced below with useful unittest output
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(item,)) for item in requests]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len({call[1] for call in api.calls}), 2)

    def test_invalid_tool_name_is_never_returned_to_opencode(self):
        api = FakeFSAPI([
            {"function_calls": [{"name": "run_command", "arguments": {"command": "rm -rf /"}}]},
            {"text": "Je ne peux pas appeler cet outil."},
        ])
        bridge = self.make_bridge(api)
        result = bridge.complete(
            self.request([{"role": "user", "content": "Lis"}], tools=[READ_TOOL]),
            "ses-validate",
        )
        self.assertNotIn("tool_calls", result["choices"][0]["message"])
        self.assertEqual(len(api.calls), 2)
        self.assertIn("AUCUN OUTIL N'A ÉTÉ EXÉCUTÉ", api.chats[api.calls[0][1]][1])
        # The refused call was never declared, so the model is told why.
        self.assertEqual(api.client_tools[0], ["list_directory", "read_file"])

    def test_permission_refusal_and_question_answer_are_returned_with_ids(self):
        api = FakeFSAPI([
            {"function_calls": [{"name": "run_command", "arguments": {"command": "ls"}}]},
            {"text": "Je poursuis avec cette information."},
        ])
        bridge = self.make_bridge(api)
        tools = [{
            "type": "function",
            "function": {
                "name": "shell",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
        }]
        user = {"role": "user", "content": "Prépare le changement"}
        first = bridge.complete(self.request([user], tools=tools), "ses-question")
        tool_call = first["choices"][0]["message"]["tool_calls"][0]
        self.assertEqual(tool_call["function"]["name"], "shell")
        messages = [
            user,
            {"role": "assistant", "tool_calls": [tool_call]},
            {"role": "tool", "tool_call_id": tool_call["id"], "name": "shell",
             "content": "Permission denied by OpenCode"},
        ]
        bridge.complete(self.request(messages, tools=tools), "ses-question")
        results = api.tool_results[1]
        self.assertEqual(results[0]["callId"], tool_call["id"])
        self.assertTrue(results[0]["isError"])
        self.assertIn("Permission denied", results[0]["output"])
        self.assertEqual(_tool_result_status({}, "Permission denied by OpenCode", "shell"), "permission_refused")
        self.assertEqual(_tool_result_status({}, "Command interrupted", "shell"), "interrupted")
        self.assertEqual(_tool_result_status({}, "Operation timed out", "shell"), "timeout")
        self.assertEqual(_tool_result_status({}, "Exit code: 0", "shell"), "success")

    def test_model_switch_keeps_fs_chat_and_uses_new_agent_id(self):
        api = FakeFSAPI([{"text": "A"}, {"text": "B"}])
        bridge = self.make_bridge(api)
        bridge.complete(self.request([{"role": "user", "content": "A"}]), "ses-switch")
        messages = [
            {"role": "user", "content": "A"},
            {"role": "assistant", "content": "A"},
            {"role": "user", "content": "B"},
        ]
        bridge.complete(self.request(messages, model="fable-5.2"), "ses-switch")
        self.assertEqual(api.calls[0][1], api.calls[1][1])
        self.assertEqual(api.calls[1][3], 906)

    def test_timeout_is_explicit_and_never_retries_mutating_chat_create(self):
        api = FakeFSAPI([asyncio.TimeoutError("simulated timeout")])
        bridge = self.make_bridge(api)
        request = self.request([{"role": "user", "content": "Démarre"}])
        with self.assertRaises(BridgeError) as caught:
            bridge.complete(request, "ses-timeout")
        self.assertEqual(caught.exception.status, 504)
        self.assertEqual(caught.exception.code, "upstream_timeout")
        self.assertEqual(len(api.calls), 1)

    def test_interrupted_stream_reconnects_from_last_event_id(self):
        api = FakeFSAPI()
        partial = [
            {"event": "stream.open", "data": {"chat_id": "fs-partial"}, "last_event_id": "20"},
            {"event": "response.output_text.delta", "data": {"delta": "bonjour"}, "last_event_id": "21"},
        ]

        async def create_chat(**_kwargs):
            raise IncompleteSSEStream(partial, OSError("connection reset"))

        api.create_chat = create_chat
        api.reconnect_result = {"text": " après reprise"}
        bridge = self.make_bridge(api)
        result = bridge.complete(self.request([{"role": "user", "content": "Réponds"}]), "ses-reconnect")
        self.assertEqual(result["choices"][0]["message"]["content"], "bonjour après reprise")
        self.assertEqual(bridge.store.get("ses-reconnect")["fs_chat_id"], "fs-partial")

    def test_missing_session_is_explicit(self):
        bridge = self.make_bridge(FakeFSAPI())
        with self.assertRaises(BridgeError) as caught:
            bridge.complete(self.request([{"role": "user", "content": "test"}]), None)
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(caught.exception.code, "opencode_session_required")


if __name__ == "__main__":
    unittest.main()
