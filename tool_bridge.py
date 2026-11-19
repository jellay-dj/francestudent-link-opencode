"""Bridge between France Student's native client tools and OpenCode tools.

France Student exposes a native client-tool protocol: a chat declares the
tools the client is able to execute, the model answers with a ``function_call``
output item, and the client answers with a ``toolResults`` entry. The tool
names and their argument schemas are fixed by France Student.

OpenCode, on the other hand, has its own tool names and schemas, and it
changes them between versions (and between models: a GPT model gets ``patch``
while other models get ``edit`` and ``write``). The mapping below is
therefore resolved at request time against the tools the request really
carries, never assumed.

The France Student schemas were observed from the live API; see
``docs/FS_CLIENT_TOOLS.md`` for the raw evidence.
"""

import json
import os


# France Student client tools and the arguments the model emits for them.
FS_CLIENT_TOOLS = {
    "list_directory": {
        "path": "string",
        "depth": "integer",
    },
    "read_file": {
        "path": "string",
    },
    "search_files": {
        "query": "string",
        "path": "string",
        "max_results": "integer",
    },
    "edit_file": {
        "path": "string",
        "old_text": "string",
        "new_text": "string",
        "replace_all": "boolean",
    },
    "write_file": {
        "path": "string",
        "content": "string",
    },
    "run_command": {
        "command": "string",
        "cwd": "string",
        "timeout_seconds": "integer",
    },
}

# For every France Student tool: the OpenCode tools that can serve it, in
# order of preference, and the France Student argument names mapped to the
# candidate OpenCode argument names.
FS_TO_OPENCODE = {
    "read_file": {
        "tools": ["read", "readfile", "read_file"],
        "args": {"path": ["path", "filePath", "file_path"]},
    },
    "list_directory": {
        "tools": ["list", "ls", "read"],
        "args": {"path": ["path", "filePath"]},
    },
    "search_files": {
        "tools": ["grep", "search", "search_files"],
        "args": {
            "query": ["pattern", "query", "regex"],
            "path": ["path"],
            "max_results": ["limit", "max_results"],
        },
    },
    "run_command": {
        "tools": ["shell", "bash", "run_command"],
        "args": {
            "command": ["command"],
            "cwd": ["workdir", "cwd"],
            "timeout_seconds": ["timeout"],
        },
    },
    "write_file": {
        "tools": ["write", "writefile", "write_file"],
        "args": {
            "path": ["path", "filePath", "file_path"],
            "content": ["content"],
        },
    },
    "edit_file": {
        "tools": ["edit", "edit_file", "str_replace_editor"],
        "args": {
            "path": ["path", "filePath", "file_path"],
            "old_text": ["oldString", "old_string", "oldText"],
            "new_text": ["newString", "new_string", "newText"],
            "replace_all": ["replaceAll", "replace_all"],
        },
    },
}

# When OpenCode only offers its unified "patch" tool, the France Student
# edit and write tools are translated into a patch document instead.
FS_TO_PATCH = {
    "write_file": "write_file",
    "edit_file": "edit_file",
}

# OpenCode arguments that hold a filesystem path and therefore have to be
# resolved against the session working directory.
_PATH_ARGUMENTS = ("filePath", "path", "file_path")

# OpenCode expects a timeout in milliseconds, France Student uses seconds.
_TIMEOUT_SCALE = 1000


def _tool_name(tool):
    if not isinstance(tool, dict):
        return None
    function = tool.get("function", tool)
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    return name if isinstance(name, str) else None


def _tool_properties(tool):
    function = tool.get("function", tool) if isinstance(tool, dict) else {}
    if not isinstance(function, dict):
        return {}
    parameters = function.get("parameters")
    if not isinstance(parameters, dict):
        return {}
    properties = parameters.get("properties")
    return properties if isinstance(properties, dict) else {}


def build_tool_plan(tools):
    """Resolve the France Student tools to declare for an OpenCode request.

    Returns ``(client_tools, plan)`` where ``client_tools`` are the France
    Student tool names to declare in the chat and ``plan`` maps each of them
    to the OpenCode tool that will execute it.
    """
    available = {}
    for tool in tools or []:
        name = _tool_name(tool)
        if name:
            available.setdefault(name, tool)

    plan = {}
    for fs_tool, spec in FS_TO_OPENCODE.items():
        for candidate in spec["tools"]:
            if candidate not in available:
                continue
            properties = _tool_properties(available[candidate])
            arguments = {}
            for fs_arg, candidates in spec["args"].items():
                for name in candidates:
                    if name in properties:
                        arguments[fs_arg] = name
                        break
                else:
                    # The tool declares no properties: fall back to the
                    # canonical name of the first candidate.
                    if not properties:
                        arguments[fs_arg] = candidates[0]
            # Only declare the France Student tool when the arguments it
            # needs can actually be expressed in the OpenCode tool.
            if _required_arguments_available(fs_tool, arguments):
                plan[fs_tool] = {
                    "tool": candidate,
                    "args": arguments,
                    "properties": properties,
                }
                break

    # France Student edit and write tools fall back to OpenCode's patch tool.
    if "patch" in available and "patchText" in _tool_properties(available["patch"]):
        for fs_tool, kind in FS_TO_PATCH.items():
            if fs_tool in plan:
                continue
            plan[fs_tool] = {
                "tool": "patch",
                "args": {},
                "properties": _tool_properties(available["patch"]),
                "patch": kind,
            }

    client_tools = sorted(plan)
    return client_tools, plan


def _required_arguments_available(fs_tool, arguments):
    """Check the France Student tool can be expressed with those arguments."""
    required = {
        "read_file": ("path",),
        "list_directory": ("path",),
        "search_files": ("query",),
        "run_command": ("command",),
        "write_file": ("path", "content"),
        "edit_file": ("path", "old_text", "new_text"),
    }.get(fs_tool, ())
    return all(name in arguments for name in required)


def client_tools_for(tools):
    """Return the France Student client tools covering an OpenCode request."""
    return build_tool_plan(tools)[0]


def supports_native_tools(tools):
    return bool(client_tools_for(tools))


def _resolve_path(value, directory):
    """Turn a France Student relative path into an absolute OpenCode path."""
    if not isinstance(value, str) or not value:
        return value
    if os.path.isabs(value) or not directory:
        return value
    return os.path.normpath(os.path.join(directory, value))


def _relative_path(value, directory):
    """Express a path relative to the working directory when possible."""
    if not isinstance(value, str) or not value or not directory:
        return value
    if not os.path.isabs(value):
        return value.replace("\\", "/")
    try:
        relative = os.path.relpath(value, directory)
    except ValueError:
        return value.replace("\\", "/")
    if relative.startswith(".."):
        return value.replace("\\", "/")
    return relative.replace("\\", "/")


def translate_arguments(fs_tool, arguments, directory=None, plan_entry=None):
    """Translate France Student call arguments into OpenCode arguments."""
    entry = plan_entry or {}
    mapping = entry.get("args") or {}
    translated = {}
    for fs_key, value in (arguments or {}).items():
        opencode_key = mapping.get(fs_key)
        if opencode_key is None:
            continue
        if opencode_key in _PATH_ARGUMENTS:
            value = _resolve_path(value, directory)
        elif opencode_key == "timeout" and isinstance(value, (int, float)):
            value = int(value * _TIMEOUT_SCALE)
        translated[opencode_key] = value
    return translated


def _read_lines(path):
    """Read a local file as text lines, or None when it is not readable."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().splitlines()
    except OSError:
        return None


def _line_level_change(path, old_text, new_text):
    """Turn a substring replacement into the changed lines.

    France Student replaces a piece of text inside a line, while OpenCode
    applies line based patches. Reading the file locally lets the bridge
    express the change the way OpenCode expects.
    """
    lines = _read_lines(path)
    if lines is None or not old_text:
        return None
    for index, line in enumerate(lines):
        if old_text in line:
            updated = line.replace(old_text, new_text, 1)
            return [lines[index], updated]
    return None


def _patch_document(kind, arguments, directory):
    """Build an OpenCode patch document from a France Student edit or write."""
    path = _relative_path(arguments.get("path"), directory)
    lines = ["*** Begin Patch"]
    if kind == "write_file":
        lines.append(f"*** Add File: {path}")
        content = arguments.get("content") or ""
        for line in content.splitlines() or [""]:
            lines.append("+" + line)
    else:
        absolute = arguments.get("path")
        if directory and isinstance(absolute, str) and not os.path.isabs(absolute):
            absolute = os.path.join(directory, absolute)
        change = None
        if absolute:
            change = _line_level_change(
                absolute,
                arguments.get("old_text") or "",
                arguments.get("new_text") or "",
            )
        lines.append(f"*** Update File: {path}")
        lines.append("@@")
        if change:
            lines.append("-" + change[0])
            lines.append("+" + change[1])
        else:
            old_text = arguments.get("old_text") or ""
            new_text = arguments.get("new_text") or ""
            for line in old_text.splitlines() or [""]:
                lines.append("-" + line)
            for line in new_text.splitlines() or [""]:
                lines.append("+" + line)
    lines.append("*** End Patch")
    return "\n".join(lines)


def translate_call(fs_tool, arguments, call_id, directory=None, plan=None):
    """Build the OpenAI tool call that OpenCode will execute.

    ``call_id`` is the identifier France Student expects back in
    ``toolResults``. The OpenAI tool call id is set to it so the correlation
    survives the round trip through OpenCode.
    """
    entry = (plan or {}).get(fs_tool)
    if not entry:
        return None

    if entry.get("patch"):
        patch_text = _patch_document(
            entry["patch"], arguments, directory
        )
        payload = {"patchText": patch_text}
    else:
        payload = translate_arguments(
            fs_tool, arguments, directory, entry
        )

    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": entry["tool"],
            "arguments": json.dumps(payload, ensure_ascii=False),
        },
    }


def parse_arguments(raw):
    """Parse the JSON arguments of a France Student function call."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
