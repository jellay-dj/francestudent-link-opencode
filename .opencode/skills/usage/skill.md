# Skill : usage

Ce skill permet de consulter l'usage et les quotas France Student depuis
OpenCode, en invoquant l'agent `@usage`.

## Utilisation

Dans OpenCode, invoquez l'agent :

```
@usage
```

Ou avec un message explicite :

```
@usage quel est mon usage France Student ?
```

## Ce qui se passe

L'agent `@usage` est géré directement par le pont France Student (pas par un
modèle). Il appelle l'endpoint local `GET /usage` du pont et retourne un
rapport lisible :

- **Cote pont** : messages par heure (utilisés/restants/limite), nouvelles
  conversations par jour (utilisées/restantes/limite)
- **Cote France Student** : budget chat utilisé en %, remise à zéro
- **Limites de taux** : buckets actifs avec utilisations
- **Tokens** : total, prompt, completion, reasoning

## Exemple de sortie

```
Usage et quotas France Student
================================

Cote pont (guards bridges) :
  Messages par heure : 5/60 (reste 55)
  Nouvelles conversations par jour : 2/40 (reste 38)

Cote France Student (compte) :
  Budget chat utilise : 2.4% (reste 97.6%)
  Remise a zero : 2026-11-21T04:00:00.000003142Z

Limites de taux actives :
  transcript-upload-user-daily-v1 : 0/5 (reste 5, 100%)
  user-invite-user-monthly-v1 : 0/5 (reste 5, 100%)

Consommation de tokens :
  Total : 19,862,017
  Prompt : 17,260,847
  Completion : 2,591,317
  Reasoning : 1,210,379

Requete effectuee via GET /usage sur le pont local.
```

## Dépannage

Si vous recevez une erreur :

1. Verifiez que le pont est lance (`python bridge_server.py`)
2. Verifiez que `http://127.0.0.1:8765/health` repond `authenticated: true`
3. Verifiez que votre session France Student est exportee
   (`scripts/fs_session_login.js`)

## Fichiers lies

- `fs_actions.py` : fonction `get_usage` qui appelle `/usage`
- `agentic_bridge.py` : logique du pont, dont l'agent `@usage`
- `bridge_server.py` : serveur Flask exposant `/usage` et gérant l'agent
- `config/config.py` : variable `FS_USAGE_AGENT` (défaut: usage)