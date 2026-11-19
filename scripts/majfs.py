"""Refresh the France Student model list and apply it to OpenCode.

Used by the `@majfs` agent and by hand:

    python scripts/majfs.py

It forces a live catalogue refresh on the bridge, rewrites only the
France Student provider of the global OpenCode configuration, and prints
what changed.
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.export_opencode_config import (  # noqa: E402
    apply_config,
    build_config,
    install_agents,
    load_models,
)


def opencode_config_path():
    """Return the global OpenCode configuration of this machine."""
    home = Path.home()
    candidates = [
        home / ".config" / "opencode" / "opencode.json",
        home / ".config" / "opencode" / "opencode.jsonc",
    ]
    appdata = home / "AppData" / "Roaming" / "opencode"
    candidates.extend([
        appdata / "opencode.json",
        appdata / "opencode.jsonc",
    ])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def read_models(target):
    try:
        payload = json.loads(Path(target).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    provider = (payload.get("providers") or {}).get("france-student") or {}
    return provider.get("models") or {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--config",
        default=str(opencode_config_path()),
        help="OpenCode configuration to update.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print the catalogue, do not touch the configuration.",
    )
    parser.add_argument(
        "--default-model",
        default="gpt-6-astra",
        help="Model OpenCode should select by default.",
    )
    args = parser.parse_args()

    try:
        entries = load_models(args.base_url)
    except RuntimeError as exc:
        print(f"Echec : {exc}", file=sys.stderr)
        print(
            "Le pont doit tourner. Lance run.bat (ou ouvre OpenCode, "
            "le plugin le demarre tout seul), puis reessaye.",
            file=sys.stderr,
        )
        return 1

    print(f"Catalogue France Student : {len(entries)} modeles actifs")
    for model_id, entry in sorted(entries.items()):
        print(f"  - {model_id}  ({entry.get('name', model_id)})")

    if args.dry_run:
        return 0

    target = Path(args.config).expanduser()
    before = read_models(target)
    config = build_config(args.base_url, entries, ROOT / ".opencode" / "plugins" / "france-student-session")
    default_model = f"france-student/{args.default_model}" if args.default_model in entries else None
    try:
        apply_config(target, config, default_model)
    except RuntimeError as exc:
        print(f"Echec : {exc}", file=sys.stderr)
        return 1

    installed = install_agents(target)
    if installed:
        print(f"Agents installes : {', '.join(installed)}")
    if default_model:
        print(f"Modele par defaut : {default_model}")

    after = read_models(target)
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    renamed = sorted(
        model for model in set(before) & set(after)
        if before[model].get("name") != after[model].get("name")
    )
    print()
    print(f"Configuration mise a jour : {target}")
    print(f"  ajoutes   : {', '.join(added) if added else 'aucun'}")
    print(f"  supprimes : {', '.join(removed) if removed else 'aucun'}")
    if renamed:
        print(f"  renommes  : {', '.join(renamed)}")
    if not added and not removed and not renamed:
        print("  aucun changement : la liste etait deja a jour.")
    print()
    print("Recharge OpenCode pour voir les nouveaux modeles (/models).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
