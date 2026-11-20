"""Deterministic actions triggered by an OpenCode agent.

Some OpenCode agents are commands in disguise: "majfs" refreshes the France
Student model list. Running them through the model would need the agent's
system prompt, which the bridge deliberately does not forward (the models
refuse to act when the request looks like an external agent harness).

So the bridge performs these actions itself: it costs no France Student
message and always behaves the same way.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path


logger = logging.getLogger("france_student_bridge.actions")

ROOT = Path(__file__).resolve().parent


def _opencode_config_path():
    home = Path.home()
    candidates = [
        home / ".config" / "opencode" / "opencode.json",
        home / ".config" / "opencode" / "opencode.jsonc",
        home / "AppData" / "Roaming" / "opencode" / "opencode.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _read_models(target):
    try:
        payload = json.loads(Path(target).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    provider = (payload.get("providers") or {}).get("france-student") or {}
    return provider.get("models") or {}


def refresh_models(base_url="http://127.0.0.1:8765", config_path=None):
    """Refresh the live catalogue and apply it to the OpenCode config.

    Returns a human readable report. Never raises for an expected failure.
    """
    target = Path(config_path or _opencode_config_path())
    script = ROOT / "scripts" / "export_opencode_config.py"
    if not script.exists():
        return "Le script de mise a jour est introuvable : " + str(script)

    command = [
        sys.executable,
        str(script),
        "--base-url",
        base_url,
        "--apply-config",
        str(target),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(ROOT),
        )
    except subprocess.TimeoutExpired:
        return "La mise a jour du catalogue a depasse le delai de 5 minutes."
    except OSError as exc:
        return f"La mise a jour du catalogue a echoue ({type(exc).__name__})."

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return "La mise a jour du catalogue a echoue :\n" + detail[:800]

    return (result.stdout or "").strip() or "Catalogue mis a jour."


def report_refresh(base_url="http://127.0.0.1:8765", config_path=None):
    """Same as :func:`refresh_models` but with a diff summary."""
    target = Path(config_path or _opencode_config_path())
    before = _read_models(target)
    report = refresh_models(base_url, target)
    after = _read_models(target)
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    lines = [report, ""]
    lines.append(f"Modeles dans la configuration : {len(after)}")
    lines.append(f"  ajoutes   : {', '.join(added) if added else 'aucun'}")
    lines.append(f"  supprimes : {', '.join(removed) if removed else 'aucun'}")
    lines.append("")
    lines.append("Recharge l'application pour voir les nouveaux modeles (/models).")
    return "\n".join(lines)


def test_connection(base_url="http://127.0.0.1:8765"):
    """Test the connection to France Student by sending a simple message.

    Sends ``$opencodetest`` as the user message and returns the model's
    answer. Used by the ``@test`` agent to verify the bridge is working.
    """
    import json
    import urllib.request

    payload = json.dumps({
        "messages": [{"role": "user", "content": "$opencodetest"}],
        "model": "gpt-6-astra",
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        return f"Echec du test de connexion a France Student : {type(exc).__name__}: {exc}"

    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})
    content = message.get("content", "")
    model = data.get("model", "inconnu")
    finish_reason = choice.get("finish_reason", "inconnu")

    lines = [
        f"Test de connexion a France Student reussi.",
        f"Modele utilise : {model}",
        f"Statut : {finish_reason}",
        "",
        "Reponse du modele :",
        content or "[vide]",
    ]
    return "\n".join(lines)
