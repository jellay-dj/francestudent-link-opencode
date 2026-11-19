"""Write an OpenCode V2 provider config using the bridge's live /v1/models."""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

MODEL_CATALOG_TIMEOUT_SECONDS = 180
OPENCODE_HEADER_TIMEOUT_MS = 20 * 60 * 1000
OPENCODE_CHUNK_TIMEOUT_MS = 20 * 60 * 1000
OPENCODE_REQUEST_TIMEOUT_MS = 30 * 60 * 1000

# The model OpenCode selects by default. Astra is the most reliable agent for
# tool use; the bridge falls back to the others when one is refused.
DEFAULT_MODEL = "france-student/gpt-6-astra"


def load_models(base_url):
    url = base_url.rstrip("/") + "/v1/models?refresh=true"
    try:
        with urlopen(url, timeout=MODEL_CATALOG_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Bridge model list unavailable at {url}: {type(exc).__name__}") from exc

    models = {}
    for entry in payload.get("data", []):
        model_id = entry.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        if entry.get("status") == "inactive":
            continue
        models[model_id] = {
            "modelID": model_id,
            "name": entry.get("fs_name") or model_id,
            "capabilities": {
                "tools": True,
                "input": ["text"],
                "output": ["text"],
            },
        }
    if not models:
        raise RuntimeError("The bridge returned no active models.")
    return models


def build_config(base_url, model_entries, plugin_path):
    if not model_entries:
        raise RuntimeError("The bridge returned no active models.")
    return {
        "$schema": "https://opencode.ai/config.json",
        "plugins": [str(Path(plugin_path).resolve())],
        "providers": {
            "france-student": {
                "name": "France Student",
                "package": "@opencode/ai/providers/openai-compatible",
                "settings": {
                    "baseURL": base_url.rstrip("/") + "/v1",
                    "headerTimeout": OPENCODE_HEADER_TIMEOUT_MS,
                    "chunkTimeout": OPENCODE_CHUNK_TIMEOUT_MS,
                    "timeout": OPENCODE_REQUEST_TIMEOUT_MS,
                },
                "models": model_entries,
            }
        },
    }


def install_agents(target_config_path):
    """Install the project agents in the global OpenCode agent folder.

    The agent files stay the single source of truth in the repository; they
    are copied to the global folder so they are available in every project.
    """
    source_dir = Path(__file__).resolve().parent.parent / ".opencode" / "agents"
    if not source_dir.is_dir():
        return []
    destination_dir = Path(target_config_path).expanduser().parent / "agents"
    installed = []
    for source in sorted(source_dir.glob("*.md")):
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / source.name
        content = source.read_text(encoding="utf-8")
        if destination.exists() and destination.read_text(encoding="utf-8") == content:
            continue
        destination.write_text(content, encoding="utf-8")
        installed.append(destination.name)
    return installed


def apply_config(target_path, generated_config, default_model=None):
    target = Path(target_path).expanduser().resolve()
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        existing = {"$schema": "https://opencode.ai/config.json"}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Cannot safely merge OpenCode config at {target}: {type(exc).__name__}. "
            "No existing config was changed."
        ) from exc
    if not isinstance(existing, dict):
        raise RuntimeError("OpenCode config root must be a JSON object; no file was changed.")

    providers = existing.setdefault("providers", {})
    if not isinstance(providers, dict):
        raise RuntimeError("OpenCode config providers must be an object; no file was changed.")
    providers["france-student"] = generated_config["providers"]["france-student"]

    plugins = existing.setdefault("plugins", [])
    if not isinstance(plugins, list):
        raise RuntimeError("OpenCode config plugins must be an array; no file was changed.")
    session_plugin = generated_config["plugins"][0]
    if session_plugin not in plugins:
        plugins.append(session_plugin)

    if default_model:
        existing["model"] = default_model

    temporary = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(f"Could not write OpenCode config: {type(exc).__name__}.") from exc
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--output", default="opencode.france-student.generated.json")
    parser.add_argument(
        "--plugin-path",
        default=str(Path(__file__).resolve().parent.parent / ".opencode" / "plugins" / "france-student-session"),
    )
    parser.add_argument(
        "--apply-config",
        help="Merge the live France Student provider into this OpenCode JSON config, preserving other settings.",
    )
    parser.add_argument(
        "--default-model",
        default=DEFAULT_MODEL,
        help="Model OpenCode selects by default (provider/model).",
    )
    args = parser.parse_args()

    try:
        model_entries = load_models(args.base_url)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    default_model = None
    if args.default_model:
        provider_id, _, model_id = args.default_model.partition("/")
        if model_id not in model_entries:
            print(
                f"Le modele par defaut {args.default_model!r} n'est pas dans le "
                "catalogue actif; la configuration n'est pas modifiee.",
                file=sys.stderr,
            )
            return 1
        default_model = args.default_model

    config = build_config(args.base_url, model_entries, args.plugin_path)
    with open(args.output, "w", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {len(model_entries)} active models to {args.output}")
    if args.apply_config:
        try:
            target = apply_config(args.apply_config, config, default_model)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Updated France Student models in {target}")
        if default_model:
            print(f"Default model: {default_model}")
        installed = install_agents(args.apply_config)
        if installed:
            print(f"Installed agents: {', '.join(installed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
