<p align="center">
  <img src="https://img.shields.io/badge/status-opérationnel-brightgreen?style=for-the-badge" />
  <img src="https://img.shields.io/badge/modèles-11%2F11-brightgreen?style=for-the-badge" />
  <img src="https://img.shields.io/badge/python-3.8%2B-yellow?style=for-the-badge&logo=python" />
  <img src="https://img.shields.io/badge/Windows%20%7C%20Linux%20%7C%20Mac-purple?style=for-the-badge" />
  <img src="https://img.shields.io/badge/licence-MIT-green?style=for-the-badge" />
</p>

<h1 align="center">France Student ↔ OpenCode Bridge</h1>
<p align="center"><i>Faites dialoguer OpenCode avec les modèles d'IA France Student, gratuitement et sans compte API.</i></p>

---

## C'est quoi ce projet ?

**France Student ↔ OpenCode Bridge** est un petit serveur local (Flask) qui transforme le chatbot gratuit [France Student](https://ia.francestudent.org) en une API OpenAI compatible. Votre harness IA préféré (OpenCode, Pi, Codex, Cursor...) peut ainsi utiliser les modèles France Student — GPT-6 Astra, Claude Opus 5.5, Claude Sonnet 5.5, etc. — sans avoir besoin d'une clé API payante.

Le pont utilise le **protocole d'outils natif** de France Student (`clientTools` → `function_call` → `toolResults`). Le modèle demande un outil, OpenCode l'exécute sur votre machine, et le résultat revient au modèle. Aucun protocole "maison", aucun refus d'agent externe.

---

## Ce que le bridge apporte

| Fonctionnalité | Détail |
|---|---|
| **11 modèles France Student** | GPT-6 Astra, GPT-6.2 Astra, Claude Opus 5.5, Claude Sonnet 5.5, etc. — découverts automatiquement depuis le catalogue live |
| **Outils natifs** | Lire, écrire, éditer, supprimer des fichiers ; lister des dossiers ; rechercher du texte ; exécuter des commandes shell — sur n'importe quel chemin de votre PC |
| **Boucle d'outils illimitée** | Le modèle peut enchaîner commande → écriture → lecture → commande, autant de fois que nécessaire |
| **Titre de session intelligent** | `FS JJ/MM/AA HHh modèle` — généré localement, ne consomme aucun message France Student |
| **Quotas respectés** | 60 messages/heure et 40 conversations/jour max (sous les limites publiées de 100/h et 50/j) |
| **Authentification sécurisée** | Session de votre navigateur échangée contre un jeton temporaire — aucun mot de passe n'est lu ni stocké |
| **4 agents de maintenance** | `@majfs`, `@test`, `@usage`, `@relance` pour gérer le pont sans toucher au code |

---

## Installation rapide

### 1. Télécharger le projet

```bash
git clone https://github.com/jellay-dj/francestudent-link-opencode.git
cd france-student-link-opencode
```

Ou cliquez sur le bouton vert **Code** → **Download ZIP** sur GitHub, puis extrayez l'archive.

### 2. Installer Python et les dépendances

**Python 3.8+** requis. Puis, dans le dossier du projet :

```bash
pip install -r requirements.txt
```

### 3. Connecter votre compte France Student

Le pont utilise **votre session de navigateur** — c'est vous qui vous connectez, aucun mot de passe n'est saisi ni automatisé.

```bash
# Windows
node scripts\fs_session_login.js

# Mac / Linux
node scripts/fs_session_login.js
```

Une fenêtre Chrome s'ouvre : connectez-vous à France Student, puis revenez dans le terminal et appuyez sur Entrée. Le script crée `.fs-session.json` (fichier secret, ignoré par Git — ne le partagez pas).

> Si votre compte dispose déjà d'une **clé API officielle France Student**, configurez plutôt `FS_AUTH_MODE=api_key` et `FS_API_KEY=<votre clé>` dans le fichier `.env`.

### 4. Lancer le service

**Windows** : double-cliquez sur `run.bat`

**Mac / Linux** :

```bash
./run.sh
```

Le service démarre sur `http://127.0.0.1:8765`. Laissez la fenêtre ouverte pendant que vous utilisez OpenCode.

### 5. Vérifier que ça marche

Dans un second terminal :

```bash
curl http://localhost:8765/health
```

Vous devez voir : `"status":"ok"` et `"authenticated":true`.

---

## Configurer OpenCode

Le pont expose une API OpenAI compatible sur `http://127.0.0.1:8765/v1`.

### Depuis OpenCode (Windows)

Dans PowerShell, allez explicitement dans le dossier du projet :

```powershell
$bridge = Join-Path $env:USERPROFILE 'Documents\Jules\Opencode bridge\france-student-bridge'
Set-Location -LiteralPath $bridge
python .\scripts\export_opencode_config.py --apply-config (Join-Path $env:USERPROFILE '.config\opencode\opencode.json')
```

Ce script :
- récupère le catalogue France Student en direct,
- remplace uniquement la section `providers.france-student` de votre configuration OpenCode,
- ajoute le plugin de session France Student s'il manque,
- préserve vos autres providers, plugins et modèle par défaut.

Puis rechargez OpenCode (`Ctrl+Shift+P` → "Reload Window" ou utilisez le CLI OpenCode : `& $openCodeCli reload`).

Les modèles apparaissent sous `france-student/<id>` (ex: `france-student/gpt-6-astra`).

---

## Utiliser l'API

Le pont écoute sur `http://localhost:8765`. Tous les endpoints sont compatibles OpenAI.

### Chat simple

```bash
curl -X POST http://localhost:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-OpenCode-Session-ID: ma-session" \
  -d '{"model":"gpt-6-astra","messages":[{"role":"user","content":"Expliquez le big bang en 2 phrases"}],"stream":false}'
```

### Chat avec outils (lecture de fichier, shell, etc.)

```bash
curl -X POST http://localhost:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-OpenCode-Session-ID: ma-session" \
  -H "X-OpenCode-Directory: C:/mon/projet" \
  -d '{"model":"gpt-6-astra","messages":[{"role":"user","content":"Lisez le fichier NOTES.md"}],"stream":false,"tools":[{"function":{"name":"read","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}}]}'
```

### Génération d'images

```bash
curl -X POST http://localhost:8765/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Un cercle rouge centré sur fond blanc","n":1,"size":"1024x1024","response_format":"url"}'
```

---

## Les en-têtes OpenCode

| En-tête | Rôle |
|---|---|
| `X-OpenCode-Session-ID` | Isole une conversation France Student par session OpenCode |
| `X-OpenCode-Request-Kind` | `primary` (défaut), `title` (géré localement, 0 message FS) |
| `X-OpenCode-Directory` | Dossier de travail pour résoudre les chemins relatifs |

---

## Les 4 agents de maintenance

Le pont inclut 4 agents qui s'exécutent directement (sans passer par un modèle France Student) :

| Agent | Rôle | Commande OpenCode |
|---|---|---|
| `@majfs` | Rafraîchit le catalogue des modèles France Student depuis le catalogue live | `@majfs` |
| `@test` | Teste la connexion à France Student en envoyant `$opencodetest` | `@test` |
| `@usage` | Affiche les quotas et l'usage France Student (messages/heure, conversations/jour, budget chat, tokens) | `@usage` |
| `@relance` | Donne les instructions pour relancer le pont et OpenCode | `@relance` |

### Exemple avec `@usage`

```
@usage
```

Renvoie :

```
Usage et quotas France Student
================================

Cote pont (guards bridges) :
  Messages par heure : 5/60 (reste 55)
  Nouvelles conversations par jour : 2/40 (reste 38)

Cote France Student (compte) :
  Budget chat utilisé : 2.4% (reste 97.6%)
  Remise à zéro : 2026-11-21T04:00:00.000003142Z

Consommation de tokens :
  Total : 19,862,017
  Prompt : 17,260,847
  Completion : 2,591,317
```

---

## Gestion des quotas

France Student publie des limites : **50 nouvelles conversations par jour** et **100 messages de chat par heure**. Le pont reste volontairement en dessous :

| Réglage | Valeur par défaut | Effet |
|---|---|---|
| `FS_MAX_MESSAGES_PER_HOUR` | `60` | Fenêtre glissante ; une requête attend son tour |
| `FS_MAX_NEW_CHATS_PER_DAY` | `40` | Une session OpenCode = une conversation France Student |

Le titre de session est produit localement : **zéro message France Student consommé** pour nommer une nouvelle conversation.

Consultez l'état en temps réel sur `http://localhost:8765/usage`.

---

## Sécurité

- Aucun mot de passe n'est lu ni automatisé : vous vous connectez vous-même à France Student dans votre navigateur
- Le cookie de session vit dans `.fs-session.json`, sur votre machine, et n'est jamais journalisé ni partagé
- Une **clé API officielle** peut être utilisée à la place (`FS_AUTH_MODE=api_key`)
- Toutes les connexions vers France Student se font en HTTPS
- Les fichiers sensibles (`.env`, `.fs-session.json`, `store.json`, `sessions.sqlite3`) sont ignorés par Git

---

## Architecture

```
[OpenCode / Pi / Codex / Cursor]
           │
           v
[Bridge Service :8765]  ←  Ce projet (Flask + Python)
           │
           v
[api.francestudent.ai]  ←  API publique France Student
           │
           v
[GPT-6 Astra | Claude Opus 5.5 | ...]
```

---

## Structure du dépôt

```
france-student-link-opencode/
├── bridge_server.py     # Serveur Flask — point d'entrée REST
├── agentic_bridge.py    # Boucle de conversation, outils, quotas, déduplication
├── auth.py              # Session navigateur ou clé API, refresh automatique du jeton
├── api_client.py        # Client HTTP vers l'API France Student
├── tool_bridge.py       # Correspondance outils France Student ↔ outils OpenCode
├── tool_loop.py         # Boucle d'outils client-side
├── rate_limiter.py      # Quotas glissants (messages/h, conversations/jour)
├── session_store.py     # Association session OpenCode ↔ conversation FS (SQLite)
├── sse_parser.py        # Parsing du flux SSE temps réel
├── openai_adapter.py    # Conversion réponses FS → format OpenAI
├── image_handler.py     # Vision : upload + stockage des images générées
├── model_catalog.py     # Catalogue OpenAI + alias de modèles
├── model_health.py      # Suivi des modèles refusés/parkés par France Student
├── config/config.py     # Configuration centralisée (quotas, timeouts, etc.)
├── fs_actions.py        # Actions déterministes (majfs, test, usage, relance)
├── scripts/majfs.py     # Rafraîchit le catalogue et la config OpenCode
├── scripts/fs_session_login.js  # Exporte votre session navigateur
├── scripts/export_opencode_config.py  # Met à jour votre configuration OpenCode
├── tests/               # 49 tests unitaires
├── docs/                # Documentation de référence (FS_CLIENT_TOOLS, FS_API_ACCESS, etc.)
├── run.bat              # Lancement Windows
├── run.sh               # Lancement Mac / Linux
├── .env.example         # Modèle de configuration (à copier en .env)
└── .gitignore           # Protège les données sensibles
```

---

## Avertissement

> Ce projet s'appuie sur l'API publique de France Student (`https://api.francestudent.ai/v3/api-docs`). L'authentification utilise votre propre session de navigateur, ou une clé API officielle si votre compte y a accès.
>
> Le bridge peut cesser de fonctionner si France Student modifie son API ou ses limites.
>
> Ce projet n'est **pas affilié à France Student**. C'est un outil communautaire open-source. Utilisez-le de façon raisonnable : ne spammez pas l'API, ne contournez pas les limites de rate limiting.

---

## Licence

MIT — faites-en ce que vous voulez. Une étoile sur GitHub fait toujours plaisir.

<p align="center">
  <a href="https://github.com/jellay-dj/francestudent-link-opencode">
    <img src="https://img.shields.io/github/stars/jellay-dj/francestudent-link-opencode?style=social" />
  </a>
</p>