"""Script de test de tous les modèles France Student via le bridge.

Test chaque modèle du catalogue avec une requête simple et affiche le
résultat (succès / échec, temps de réponse, erreur éventuelle).

Usage : python test_all_models.py [session_id]
"""

import json
import sys
import time
import uuid
import urllib.request
import urllib.error

# Force UTF-8 output on Windows console.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "http://127.0.0.1:8765"
SESSION_ID = sys.argv[1] if len(sys.argv) > 1 else f"test-models-{uuid.uuid4().hex[:8]}"


def http_get(path, timeout=30):
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_post(path, payload, session_id=None, timeout=120):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-OpenCode-Session-ID": session_id or SESSION_ID,
            "X-OpenCode-Directory": ".",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": True, "status": e.code, "body": body}


def safe_print(*args, **kwargs):
    """Print without crashing on non-encodable characters."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        new_args = tuple(
            a.encode("ascii", errors="replace").decode("ascii") if isinstance(a, str) else a
            for a in args
        )
        print(*new_args, **kwargs)


def main():
    # Récupérer le catalogue
    safe_print("=== Recuperation du catalogue ===")
    try:
        models_data = http_get("/v1/models")
        models = models_data.get("data", [])
    except Exception as exc:
        safe_print(f"Erreur lors de la recuperation du catalogue : {exc}")
        return 1

    if not models:
        safe_print("Aucun modele trouvé dans le catalogue.")
        return 1

    safe_print(f"{len(models)} modele(x) trouvé(x) :")
    for m in models:
        safe_print(f"  - {m.get('id')} (fs_agent_id={m.get('fs_agent_id')}, status={m.get('status')})")

    safe_print(f"\n=== Test de chaque modele (session : {SESSION_ID}) ===\n")

    results = []
    for i, model in enumerate(models, 1):
        model_id = model.get("id")
        # Session ID unique par modèle pour tester chaque modèle
        # dans une conversation France Student indépendante.
        model_session_id = f"{SESSION_ID}-{i}"
        safe_print(f"[{i}/{len(models)}] Test de {model_id} ... ", end="", flush=True)

        start = time.time()
        payload = {
            "messages": [{"role": "user", "content": "Dis bonjour en un seul mot."}],
            "model": model_id,
            "stream": False,
        }
        result = http_post("/v1/chat/completions", payload, session_id=model_session_id, timeout=120)
        elapsed = time.time() - start

        if result.get("error"):
            status = result.get("status", "?")
            body = result.get("body", "")
            safe_print(f"ECHEC (HTTP {status}) apres {elapsed:.1f}s")
            try:
                err = json.loads(body)
                msg = err.get("error", {}).get("message", body[:120])
            except Exception:
                msg = body[:120]
            safe_print(f"         └─ {msg}")
            results.append((model_id, False, elapsed, msg))
        else:
            choice = result.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content", "")
            finish_reason = choice.get("finish_reason", "?")
            usage = result.get("usage", {})
            total_tokens = usage.get("total_tokens", 0)
            safe_print(f"OK ({elapsed:.1f}s, {finish_reason}, {total_tokens} tokens)")
            safe_print(f"         └─ {content[:100]}")
            results.append((model_id, True, elapsed, content))

    # Résumé
    safe_print("\n=== Résumé ===")
    success = sum(1 for _, ok, _, _ in results if ok)
    failed = len(results) - success
    safe_print(f"Total : {len(results)} | Réussis : {success} | Échoués : {failed}")
    safe_print("\nDétail :")
    for model_id, ok, elapsed, detail in results:
        status = "OK" if ok else "ECHEC"
        safe_print(f"  {model_id}: {status} ({elapsed:.1f}s) - {detail[:80]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
