import json
import os
import unittest

from tool_bridge import (
    FS_CLIENT_TOOLS,
    build_tool_plan,
    client_tools_for,
    parse_arguments,
    translate_call,
)


def _tool(name, properties=None, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
            },
        },
    }


READ = _tool("read", {"path": {"type": "string"}, "offset": {"type": "integer"},
                      "limit": {"type": "integer"}}, ["path"])
SHELL = _tool("shell", {"command": {"type": "string"}, "workdir": {"type": "string"},
                         "timeout": {"type": "integer"}, "background": {"type": "boolean"}},
              ["command"])
GREP = _tool("grep", {"pattern": {"type": "string"}, "path": {"type": "string"},
                       "limit": {"type": "integer"}}, ["pattern"])
WRITE = _tool("write", {"path": {"type": "string"}, "content": {"type": "string"}},
              ["path", "content"])
EDIT = _tool("edit", {"path": {"type": "string"}, "oldString": {"type": "string"},
                      "newString": {"type": "string"},
                      "replaceAll": {"type": "boolean"}}, ["path"])
PATCH = _tool("patch", {"patchText": {"type": "string"}}, ["patchText"])


class ToolBridgeTests(unittest.TestCase):
    def test_plan_follows_the_opencode_schemas_of_the_request(self):
        client_tools, plan = build_tool_plan([READ, SHELL, GREP])
        self.assertEqual(
            client_tools,
            ["list_directory", "read_file", "run_command", "search_files"],
        )
        self.assertEqual(plan["read_file"]["tool"], "read")
        self.assertEqual(plan["read_file"]["args"]["path"], "path")
        self.assertEqual(plan["run_command"]["tool"], "shell")
        self.assertEqual(plan["run_command"]["args"]["cwd"], "workdir")
        self.assertEqual(plan["search_files"]["tool"], "grep")
        self.assertEqual(plan["search_files"]["args"]["query"], "pattern")

    def test_unmapped_opencode_tools_are_not_declared(self):
        client_tools, _ = build_tool_plan([
            _tool("question", {"questions": {"type": "array"}}),
            _tool("webfetch", {"url": {"type": "string"}}),
        ])
        self.assertEqual(client_tools, [])

    def test_read_file_resolves_a_relative_path(self):
        _, plan = build_tool_plan([READ])
        call = translate_call(
            "read_file", {"path": "notes.md"}, "call_1", "C:/project", plan
        )
        self.assertEqual(call["id"], "call_1")
        self.assertEqual(call["function"]["name"], "read")
        self.assertEqual(
            json.loads(call["function"]["arguments"]),
            {"path": os.path.normpath("C:/project/notes.md")},
        )

    def test_absolute_paths_are_left_untouched(self):
        _, plan = build_tool_plan([READ])
        call = translate_call(
            "read_file", {"path": "C:/elsewhere/notes.md"}, "call_1", "C:/project", plan
        )
        self.assertEqual(
            json.loads(call["function"]["arguments"]),
            {"path": "C:/elsewhere/notes.md"},
        )

    def test_run_command_translates_the_timeout_to_milliseconds(self):
        _, plan = build_tool_plan([SHELL])
        call = translate_call(
            "run_command",
            {"command": "ls", "cwd": ".", "timeout_seconds": 30},
            "call_2",
            "C:/project",
            plan,
        )
        arguments = json.loads(call["function"]["arguments"])
        self.assertEqual(call["function"]["name"], "shell")
        self.assertEqual(arguments["command"], "ls")
        self.assertEqual(arguments["timeout"], 30000)
        self.assertNotIn("cwd", arguments)

    def test_edit_tool_renames_the_text_arguments(self):
        _, plan = build_tool_plan([EDIT])
        call = translate_call(
            "edit_file",
            {"path": "a.txt", "old_text": "x", "new_text": "y", "replace_all": True},
            "call_3",
            "C:/project",
            plan,
        )
        arguments = json.loads(call["function"]["arguments"])
        self.assertEqual(call["function"]["name"], "edit")
        self.assertEqual(arguments["oldString"], "x")
        self.assertEqual(arguments["newString"], "y")
        self.assertTrue(arguments["replaceAll"])
        self.assertEqual(arguments["path"], os.path.normpath("C:/project/a.txt"))

    def test_write_tool_keeps_the_content(self):
        _, plan = build_tool_plan([WRITE])
        call = translate_call(
            "write_file", {"path": "a.txt", "content": "hello"}, "call_4",
            "C:/project", plan,
        )
        arguments = json.loads(call["function"]["arguments"])
        self.assertEqual(call["function"]["name"], "write")
        self.assertEqual(arguments["content"], "hello")

    def test_patch_tool_is_used_when_edit_and_write_are_absent(self):
        client_tools, plan = build_tool_plan([READ, PATCH])
        self.assertIn("write_file", client_tools)
        self.assertIn("edit_file", client_tools)
        call = translate_call(
            "write_file", {"path": "a.txt", "content": "hello"}, "call_5",
            "C:/project", plan,
        )
        arguments = json.loads(call["function"]["arguments"])
        self.assertEqual(call["function"]["name"], "patch")
        self.assertIn("*** Begin Patch", arguments["patchText"])
        self.assertIn("*** Add File: a.txt", arguments["patchText"])
        self.assertIn("+hello", arguments["patchText"])

    def test_patch_document_for_an_edit(self):
        _, plan = build_tool_plan([PATCH])
        call = translate_call(
            "edit_file",
            {"path": "a.txt", "old_text": "old line", "new_text": "new line"},
            "call_6", "C:/project", plan,
        )
        patch_text = json.loads(call["function"]["arguments"])["patchText"]
        self.assertIn("*** Update File: a.txt", patch_text)
        self.assertIn("-old line", patch_text)
        self.assertIn("+new line", patch_text)
        self.assertTrue(patch_text.startswith("*** Begin Patch"))
        self.assertTrue(patch_text.rstrip().endswith("*** End Patch"))

    def test_unknown_client_tool_has_no_opencode_equivalent(self):
        _, plan = build_tool_plan([READ])
        self.assertIsNone(translate_call("teleport", {}, "call_7", None, plan))

    def test_arguments_parser_accepts_json_and_rejects_garbage(self):
        self.assertEqual(parse_arguments('{"a": 1}'), {"a": 1})
        self.assertEqual(parse_arguments({"a": 1}), {"a": 1})
        self.assertEqual(parse_arguments("not json"), {})
        self.assertEqual(parse_arguments(""), {})

    def test_documented_client_tool_schemas_are_complete(self):
        # These schemas were observed from the live France Student API.
        self.assertEqual(
            set(FS_CLIENT_TOOLS),
            {
                "list_directory",
                "read_file",
                "search_files",
                "edit_file",
                "write_file",
                "run_command",
            },
        )
        self.assertEqual(
            set(FS_CLIENT_TOOLS["search_files"]),
            {"query", "path", "max_results"},
        )
        self.assertEqual(
            set(FS_CLIENT_TOOLS["run_command"]),
            {"command", "cwd", "timeout_seconds"},
        )

    def test_client_tools_for_is_a_shortcut(self):
        self.assertEqual(
            client_tools_for([READ, SHELL]),
            ["list_directory", "read_file", "run_command"],
        )


if __name__ == "__main__":
    unittest.main()
