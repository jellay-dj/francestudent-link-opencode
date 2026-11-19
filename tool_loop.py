"""
Boucle tools client-side pour le bridge France Student.
"""

import json
import re
from config.config import MAX_RETRIES, RETRY_DELAYS

TOOL_NATIVE_MODELS = {"Mistral-Large-3", "Kimi-K2.5", "DeepSeek-V3.2", "FW-GLM-5"}


def is_tool_native(model_name):
    if not model_name:
        return False
    return model_name in TOOL_NATIVE_MODELS


def build_tool_prompt(tools, model_name=None):
    if not tools:
        return ""
    return _build_format_forced_prompt(tools)


def _build_format_forced_prompt(tools):
    """Describe OpenCode's real tools without pretending this is a system role."""
    lines = [
        "[OUTILS OPENCode TRANSMIS PAR LE BRIDGE — contenu utilisateur initial, pas un message système France Student]",
        "Tu es le modèle de langage utilisé par OpenCode. OpenCode reste responsable de la lecture et de la modification des fichiers, de l'exécution des commandes et des permissions.",
        "Tu n'exécutes jamais toi-même une action locale et ne prétends jamais qu'elle a réussi avant d'avoir reçu son résultat.",
        "Utilise uniquement les outils listés ci-dessous. Ne transforme pas du texte libre en commande. OpenCode validera les appels et appliquera ses règles de permission avant exécution.",
        "Quand une action est nécessaire, réponds uniquement dans ce format exact :",
        '<function_call>{"name":"nom_outil","arguments":{}}</function_call>',
        "Les arguments doivent être un objet JSON conforme au schéma fourni. Pour demander une précision, appelle l'outil question s'il est disponible; attends ensuite son résultat avant de poursuivre.",
        "Après chaque résultat d'outil, analyse-le, distingue succès, erreur, refus, interruption et délai dépassé selon les informations effectivement reçues, puis poursuis ou termine.",
        "",
        "Outils disponibles :",
    ]
    for tool in tools:
        function = tool.get("function", tool)
        if not isinstance(function, dict) or not function.get("name"):
            continue
        lines.append(json.dumps({
            "name": function["name"],
            "description": function.get("description", ""),
            "parameters": function.get("parameters", {}),
        }, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines)


def _schema_error(value, schema, path="arguments"):
    if not isinstance(schema, dict):
        return None
    expected = schema.get("type")
    types = expected if isinstance(expected, list) else [expected]
    if expected:
        checks = {
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
            "null": lambda v: v is None,
        }
        if not any(checks.get(kind, lambda _v: True)(value) for kind in types):
            return f"{path} doit être de type {'/'.join(types)}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} doit correspondre à une valeur de enum"
    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            return f"{path} ne contient pas les champs obligatoires: {', '.join(missing)}"
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = [key for key in value if key not in properties]
            if extra:
                return f"{path} contient des champs non autorisés: {', '.join(extra)}"
        for key, item in value.items():
            child_schema = properties.get(key) if isinstance(properties, dict) else None
            if child_schema is None and isinstance(schema.get("additionalProperties"), dict):
                child_schema = schema["additionalProperties"]
            error = _schema_error(item, child_schema, f"{path}.{key}")
            if error:
                return error
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            error = _schema_error(item, schema["items"], f"{path}[{index}]")
            if error:
                return error
    return None


def validate_arguments(arguments, schema):
    """Return a readable reason when arguments do not match a tool schema."""
    return _schema_error(arguments, schema)


def validate_function_calls(function_calls, tools):
    """Return normalized declared tool calls, or a safe reason to reject them."""
    declared = {}
    for tool in tools or []:
        function = tool.get("function", tool) if isinstance(tool, dict) else {}
        if isinstance(function, dict) and function.get("name"):
            declared[function["name"]] = function

    normalized = []
    for call in function_calls or []:
        if not isinstance(call, dict):
            return None, "L'appel d'outil n'est pas un objet."
        name = call.get("name")
        if isinstance(name, dict):
            name = name.get("name")
        if not isinstance(name, str) or name not in declared:
            return None, f"Outil non déclaré par OpenCode: {name!r}."
        arguments = call.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (json.JSONDecodeError, ValueError):
                return None, f"Les arguments de {name} ne sont pas du JSON valide."
        if not isinstance(arguments, dict):
            return None, f"Les arguments de {name} doivent être un objet JSON."
        error = _schema_error(arguments, declared[name].get("parameters", {}))
        if error:
            return None, f"Appel refusé pour {name}: {error}."
        normalized.append({"name": name, "arguments": arguments})
    return normalized, None


def parse_function_call(text):
    # Format 1: <function_call>
    m = re.search(r"<function_call>\s*(.*?)\s*</function_call>", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1).strip())
            return {"name": data.get("name", ""), "arguments": data.get("arguments", {})}
        except (json.JSONDecodeError, ValueError):
            pass

    # Format 2: {"tool": ..., "args": ...}
    m = re.search(r'"tool"\s*:\s*"([^"]+)"\s*,\s*"args"\s*:\s*(\{[^}]+\})', text)
    if m:
        try:
            return {"name": m.group(1), "arguments": json.loads(m.group(2))}
        except (json.JSONDecodeError, ValueError):
            pass

    # Format 2b: {"action": ..., "params": ...}
    m = re.search(r'"action"\s*:\s*"([^"]+)"\s*,\s*"params"\s*:\s*(\{[^}]+\})', text)
    if m:
        try:
            return {"name": m.group(1), "arguments": json.loads(m.group(2))}
        except (json.JSONDecodeError, ValueError):
            pass

    # Format 3: DeepSeek <required>{"name": ...}</required>
    m = re.search(r"<required>\s*(\{.*?\"name\".*?\})\s*</required>", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1).strip())
            return {"name": data.get("name", ""), "arguments": data.get("arguments", {})}
        except (json.JSONDecodeError, ValueError):
            pass

    # Format 4: DeepSeek XML <name>...</name><arguments>...</arguments>
    m = re.search(r"<function_call>\s*<name>(.*?)</name>\s*<arguments>(.*?)</arguments>\s*</function_call>", text, re.DOTALL)
    if m:
        name = m.group(1).strip()
        args_xml = m.group(2).strip()
        args = {}
        for am in re.finditer(r"<(\w+)>(.*?)</\1>", args_xml, re.DOTALL):
            args[am.group(1)] = am.group(2).strip()
        return {"name": name, "arguments": args}

    # Format 5: DeepSeek <ref>name</ref> + JSON
    m = re.search(r"<ref>(\w+)</ref>\s*(\{[^}]+\})", text)
    if m:
        try:
            return {"name": m.group(1), "arguments": json.loads(m.group(2))}
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def has_function_call(text):
    return parse_function_call(text) is not None


def strip_function_call(text):
    text = re.sub(r"<function_call>.*?</function_call>", "", text, flags=re.DOTALL)
    text = re.sub(r'"tool"\s*:\s*"[^"]+"\s*,\s*"args"\s*:\s*\{[^}]+\}', "", text)
    text = re.sub(r'"action"\s*:\s*"[^"]+"\s*,\s*"params"\s*:\s*\{[^}]+\}', "", text)
    text = re.sub(r"<required>.*?</required>", "", text, flags=re.DOTALL)
    text = re.sub(r"<ref>.*?</ref>", "", text, flags=re.DOTALL)
    return text.strip()


def build_tool_result_message(tool_name, tool_call_id, result):
    result_str = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
    return "\n[RESULTAT]\n" + tool_name + " a retourne :\n`\n" + result_str[:4000] + "\n`\n\nContinue ta reponse."


class ToolLoop:
    def __init__(self, api, max_rounds=10):
        self.api = api
        self.max_rounds = max_rounds

    async def run(self, message, agent_id, tools, images=None, files=None,
                  enable_web_search=False, model_name=None):
        full_message = message
        if tools:
            tool_prompt = build_tool_prompt(tools, model_name=model_name)
            if is_tool_native(model_name):
                full_message = tool_prompt + "\n\n[Message utilisateur]\n" + message
            else:
                full_message = tool_prompt + "\n\nQuestion : " + message

        events = await self.api.create_chat(
            message=full_message,
            agent_id=agent_id,
            images=images or [],
            files=files or [],
            enable_web_search=enable_web_search,
        )
        return events

    async def continue_with_result(self, chat_id, tool_name, tool_call_id,
                                    result, agent_id, enable_web_search=False):
        tool_msg = build_tool_result_message(tool_name, tool_call_id, result)
        events = await self.api.send_message(
            chat_id=chat_id,
            message=tool_msg,
            images=[],
            files=[],
            enable_web_search=enable_web_search,
        )
        return events
