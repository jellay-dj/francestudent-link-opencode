<p align="center">
  <img src="https://img.shields.io/badge/status-operational-brightgreen?style=for-the-badge" />
  <img src="https://img.shields.io/badge/models-12%2F12-brightgreen?style=for-the-badge" />
  <img src="https://img.shields.io/badge/python-3.8%2B-yellow?style=for-the-badge&logo=python" />
  <img src="https://img.shields.io/badge/platform-Win%20%7C%20Linux%20%7C%20Mac-purple?style=for-the-badge" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" />
</p>

<p align="center">
  <h1 align="center">France Student AI Bridge</h1>
  <p align="center"><i>Transform your favorite AI harness into a multi-model powerhouse —<br>powered by France Student's free chatbot API.</i></p>
</p>

---

## C'est quoi France Student ?

**[France Student](https://ia.francestudent.org)** est un chatbot IA en ligne gratuit propose par l'association **France Student**. Il donne acces a **12 agents d'IA** actifs — GPT et Claude — via une interface web, sans abonnement payant.

> **Pour s'inscrire** : va sur [ia.francestudent.org](https://ia.francestudent.org) → clique sur "Se connecter" → connecte-toi avec ton compte France Student (gratuit).

---

## C'est quoi ce projet ?

Ce **Bridge Service** est un serveur local qui fait le pont entre ton **harness IA prefere** (OpenCode, Pi, Codex, OpenGravity, Cursor...) et le chatbot France Student. Il expose une API REST propre qui traduit tes requetes en appels vers France Student, et te renvoie les reponses — texte, code, raisonnement, images generees — dans un format standard.

> **En clair** : ton harness peut maintenant parler aux 12 agents actuels, envoyer des images pour analyse et generer des images, gratuitement, sans quitter ton terminal.

Le pont utilise le **protocole d'outils natifs** de France Student : le modele demande un outil, OpenCode l'execute, le resultat revient au modele. Voir [`docs/FS_CLIENT_TOOLS.md`](docs/FS_CLIENT_TOOLS.md).

---

## Modeles actifs du compte (catalogue live verifie le 16/11/2026)

Le pont interroge dynamiquement `GET /chats/agents` ; n'utilise pas des valeurs figees pour ajouter ou remplacer un modele. Consulte `GET /v1/models` ou suis [`docs/FS_MODEL_REFRESH.md`](docs/FS_MODEL_REFRESH.md) pour actualiser OpenCode depuis le catalogue FS.

| Modele OpenAI | Nom France Student | Fournisseur | Agent ID |
|---------------|--------------------|-------------|----------|
| `gpt-5.6-terra` | `gpt-5.6-terra` | OpenAI | `66` |
| `gpt-5.6-luna` | `gpt-5.6-luna` | OpenAI | `65` |
| `gpt-5.6-sol` | `gpt-5.6-sol` (par defaut) | OpenAI | `64` |
| `gpt-6-sol` | `GPT 6 Sol` | OpenAI | `-1001` |
| `gpt-6-luna` | `GPT 6 Luna` | OpenAI | `-1002` |
| `gpt-6.1-sol` | `GPT 6.1 Sol` | OpenAI | `-1003` |
| `gpt-6-astra` | `GPT-6 Astra` | OpenAI | `-1004` |
| `gpt-6.1-terra` | `GPT-6.1 Terra` | OpenAI | `-1005` |
| `claude-opus-5-5` | `Claude Opus 5.5` | Anthropic | `-2001` |
| `claude-haiku-5-5` | `Claude Haiku 5.5` | Anthropic | `-2002` |
| `claude-sonnet-5-5` | `Claude Sonnet 5.5` | Anthropic | `-2003` |
| `claude-fable-5-2` | `Claude Fable 5.2` | Anthropic | `-2005` |

### Alias compatibles

- `/v1/models` utilise le champ `model` comme ID canonique et expose aussi `fs_agent_id`, `fs_name`, `status` et `aliases`.
- Les anciens alias `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano`, `claude-sonnet-4-6` et `claude-opus-4-8` restent acceptes mais sont deprecies. Ils routent vers l'agent actuel le plus proche.
- Les noms d'affichage France Student (`GPT 6 Sol`, `Claude Opus 5.5`, etc.) et les IDs numeriques restent aussi acceptes.
- Les anciens modeles sans equivalent actif (`DeepSeek-V3.2`, `Mistral-Large-3`, `Kimi-K2.5`, `gpt-oss-120b`, `FW-GLM-5`, `claude-haiku-4-5`, `claude-sonnet-5`, `claude-opus-5`) ne sont plus resolus.

### Ce que dit l'API officielle

La documentation technique de France Student est publique :
<https://api.francestudent.ai/v3/api-docs>. Une copie locale est dans
[`docs/francestudent-openapi.json`](docs/francestudent-openapi.json).
Les CGU 2026 (Livre V) exigent un Compte API distinct approuve et des Cles
API pour l'acces programmatique ; l'etat de cet acces et les limites
publiees sont detailes dans [`docs/FS_API_ACCESS.md`](docs/FS_API_ACCESS.md).

En pratique, sur ce compte :

- l'endpoint de cle API `/user/@me/api-key` repond `403` : la fonction n'est
  pas encore ouverte a ce compte ;
- le pont utilise donc la session du navigateur, echangee contre un jeton
  court via `GET /api/auth/api-token`, comme le fait l'application France
  Student ;
- les limites publiees sont **50 nouvelles conversations par jour** et
  **100 messages de chat par heure** ; le pont se tient en dessous avec
  `FS_MAX_MESSAGES_PER_HOUR` et `FS_MAX_NEW_CHATS_PER_DAY`.

Les conversations du pont sont creees dans un projet France Student dedie
(`FS_PROJECT_ID`, projet « Bridge ») et non dans l'onglet principal.

---

## Tutoriel debutant (zero code)

Tu n'as jamais touche a un terminal ? Pas de panique. Suis ces etapes dans l'ordre.

### Etape 1 — Installer Python

**Windows** : va sur [python.org](https://www.python.org/downloads/), telecharge la derniere version, lance l'installeur, et **coche la case "Add Python to PATH"** avant de cliquer Installer.

**Mac** : ouvre le Terminal (Cmd+Espace → taper "Terminal") et colle :
```bash
brew install python3
```

**Linux** : Python est deja installe. Ouvre juste ton terminal.

> Pour verifier que Python est installe : tape `python --version` dans le terminal. Tu dois voir `Python 3.x.x`.

### Etape 2 — Telecharger le projet

Clique sur le bouton vert **"Code"** en haut de cette page, puis **"Download ZIP"**.

Extrais le fichier ZIP dans un dossier (par exemple `Bureau/bridge-service`).

> Alternative : dans un terminal, tape :
> ```bash
> git clone https://github.com/jellay-dj/francestudent-link-opencode.git
> cd france-student-bridge
> ```

### Etape 3 — Installer les dependances

Ouvre un terminal (ou PowerShell sur Windows) **dans le dossier du projet** :

```bash
pip install -r requirements.txt
```

Tu vas voir des lignes defiler. Attends que ca finisse.

### Etape 4 — Connecter ton compte France Student

Le pont utilise la session de ton navigateur : **c'est toi qui te connectes**,
aucun mot de passe n'est lu ni automatise.

**Windows** : dans un terminal, a la racine du projet :

```bash
node scripts\fs_session_login.js
```

Une fenetre Chrome s'ouvre. Connecte-toi a France Student, puis reviens dans
le terminal et appuie sur `Entree`. Le script ecrit `.fs-session.json` a la
racine du projet (ce fichier est un secret : il est ignore par Git, ne le
partage pas).

**Mac / Linux** : `node scripts/fs_session_login.js`.

> Si ton compte dispose d'une **Cle API officielle**, tu peux sauter cette étape :
> mets `FS_AUTH_MODE=api_key` et `FS_API_KEY=<ta clé>` dans `.env`. Voir
> [`docs/FS_API_ACCESS.md`](docs/FS_API_ACCESS.md).

### Etape 5 — Lancer le service

**Windows** : double-clique sur `run.bat`

**Mac / Linux** : dans le terminal, tape :
```bash
./run.sh
```

Tu devrais voir :
```
Bridge Service demarre sur http://127.0.0.1:8765
```

**Laisse cette fenetre ouverte.** Le service tourne en arriere-plan. Pour l'arreter, fais `Ctrl+C`.

### Etape 6 — Tester que ca marche

Ouvre un **deuxieme terminal** (ne ferme pas le premier) et tape :

```bash
curl http://localhost:8765/health
```

Si tu vois `"status":"ok"` et `"authenticated":true` → tout fonctionne.

### Etape 7 — Envoyer ton premier message

```bash
curl -X POST http://localhost:8765/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -H "X-OpenCode-Session-ID: ma-premiere-session" ^
  -d "{\"model\":\"gpt-5.6-sol\",\"messages\":[{\"role\":\"user\",\"content\":\"Explique-moi le big bang en 2 phrases\"}]}"
```

> Sur Mac/Linux, remplace `^` par `\` a la fin de chaque ligne.

Tu recevras une reponse du modele choisi.

---

## OpenCode sous Windows

1. Installe les dependances avec `python -m pip install -r requirements.txt`, puis lance `run.bat`. Le service ecoute uniquement sur `127.0.0.1:8765` par defaut.
2. Dans PowerShell, va explicitement dans le dossier du projet avant d'executer les commandes. Sans cela, un chemin relatif comme `scripts/export_opencode_config.py` sera cherche dans le dossier courant de PowerShell (souvent `C:\Users\<utilisateur>`), pas dans le depot.

   ```powershell
   $bridge = Join-Path $env:USERPROFILE 'Documents\Jules\Opencode bridge\france-student-bridge'
   Set-Location -LiteralPath $bridge
   python .\scripts\export_opencode_config.py --apply-config (Join-Path $env:USERPROFILE '.config\opencode\opencode.json')
   ```

   Le script demande le catalogue FS en direct, remplace uniquement `providers.france-student`, conserve les autres réglages et ajoute le plugin qui associe chaque session OpenCode à son chat FS.
4. Recharge la configuration et vérifie les entrées sous `france-student/<id>`. Si `opencode` n'est pas reconnu dans PowerShell, utilise le chemin du CLI livré avec OpenCode Desktop :

   ```powershell
   $openCodeCli = Join-Path $env:LOCALAPPDATA 'Programs\ai.opencode.desktop\resources\opencode-cli.exe'
   if (-not (Test-Path -LiteralPath $openCodeCli)) { throw "CLI OpenCode introuvable : $openCodeCli" }
   & $openCodeCli reload
   & $openCodeCli models
   ```

Les délais configurés pour France Student sont de 20 minutes avant les premiers en-têtes ou entre les fragments, et de 30 minutes au total par requête OpenCode. Le bridge laisse jusqu'à 20 minutes entre les fragments SSE et borne une conversation à 30 minutes. Ces limites finies laissent aux modèles plus lents le temps de raisonner tout en préservant la possibilité d'interrompre proprement une requête.

Pour actualiser plus tard les anciens modèles lorsque FS en ajoute ou en retire, demande à l'agent OpenCode de suivre [`docs/FS_MODEL_REFRESH.md`](docs/FS_MODEL_REFRESH.md). Ce document est également indiqué dans [`AGENTS.md`](AGENTS.md), afin que l'agent connaisse le protocole de remplacement sans inventer d'IDs.

Le nom de l'exécutable CLI peut être différent selon l'installation. Sur cette machine, le binaire fourni avec l'application est `resources/opencode-cli.exe` dans le dossier d'installation OpenCode.

Le bridge doit **rester lancé** pendant que tu utilises OpenCode. `run.bat`
garde une fenetre de console ouverte : laisse-la ouverte, et ferme-la (ou
`Ctrl+C`) pour arreter le service. Pour un lancement sans fenetre visible :

```powershell
Start-Process python -ArgumentList "bridge_server.py" -WorkingDirectory $PWD -WindowStyle Hidden
```

Les conversations creees par le pont vivent dans le projet France Student
« Bridge » (`FS_PROJECT_ID`), pas dans l'onglet principal de l'application.

## Guide utilisateur avance (pour les devs)

### Installation rapide

```bash
git clone https://github.com/jellay-dj/francestudent-link-opencode.git
cd france-student-bridge
pip install -r requirements.txt
```

### Lancement

```bash
# Linux / macOS
./run.sh

# Windows
python bridge_server.py
```

### Utilisation API

Les exemples ci-dessous decrivent l'interface locale compatible OpenAI.

```bash
# Lister les modeles au format OpenAI
curl http://localhost:8765/v1/models

# Chat OpenAI, reponse JSON
curl -X POST http://localhost:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-OpenCode-Session-ID: ma-session" \
  -d '{"model":"gpt-5.6-sol","messages":[{"role":"user","content":"Ecris quick sort en Python"}],"stream":false}'

# Chat OpenAI en streaming SSE
curl -N -X POST http://localhost:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-OpenCode-Session-ID: ma-session" \
  -d '{"model":"claude-opus-5-5","messages":[{"role":"user","content":"Compte de 1 a 10"}],"stream":true}'

# Vision: image_url accepte une URL http(s) ou une data URL base64
curl -X POST http://localhost:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.6-sol","messages":[{"role":"user","content":[{"type":"text","text":"Decris cette image"},{"type":"image_url","image_url":{"url":"data:image/png;base64,VOTRE_BASE64"}}]}],"stream":false}'

# Generer une image et recevoir une URL locale
curl -X POST http://localhost:8765/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-image-1","prompt":"Un cercle rouge centre sur fond blanc","n":1,"size":"1024x1024","response_format":"url"}'

# Uploader un fichier et recuperer son UUID France Student
curl -X POST http://localhost:8765/upload \
  -F "file=@mon_image.png"
```

### Tous les endpoints

| Methode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/health` | Etat du service + auth + compteurs de quota |
| `GET` | `/usage` | Etat des quotas respectes par le pont |
| `GET` | `/models` | Modeles disponibles |
| `GET` | `/v1/models` | Catalogue et alias au format OpenAI |
| `POST` | `/auth/login` | Authentification manuelle |
| `GET` | `/auth/status` | Verifier l'auth |
| `POST` | `/chat/completions` | **Chat principal** (streaming ou JSON) |
| `POST` | `/v1/chat/completions` | Chat OpenAI multimodal + tools |
| `POST` | `/v1/images/generations` | Generation d'images par delegation |
| `POST` | `/chat/{id}/message` | Message dans un chat existant |
| `GET` | `/chat/{id}` | Historique d'un chat |
| `GET` | `/chats` | Liste des chats |
| `DELETE` | `/chat/{id}/delete` | Supprimer un chat |
| `GET` | `/chat/{id}/usage` | Consommation tokens |
| `POST` | `/upload` | Uploader fichier/image |
| `GET` | `/images/{filename}` | Servir image generee |

### Les outils dans le format OpenAI

`/v1/chat/completions` accepte les outils au format OpenAI et les renvoie au
modele. Le pont transforme les appels du modele en `tool_calls` OpenAI, puis
renvoie le resultat de l'outil au modele :

```json
{
  "choices": [{
    "index": 0,
    "finish_reason": "tool_calls",
    "message": {
      "role": "assistant",
      "content": null,
      "tool_calls": [{
        "id": "call_j5I2nOHoeaFnzibQ3kfMhBK4",
        "type": "function",
        "function": {"name": "read", "arguments": "{\"path\":\"C:/projet/NOTES.md\"}"}
      }]
    }
  }]
}
```

L'identifiant `id` est celui du modele : renvoie-le tel quel dans le message
`role: "tool"` pour que le resultat soit rattache au bon appel.

Les en-tetes `X-OpenCode-Session-ID`, `X-OpenCode-Request-Kind` et
`X-OpenCode-Directory` sont lus par le pont. Le premier isole une
conversation France Student par session ; le dernier sert a resoudre les
chemins relatifs que le modele produit.

### Format de reponse

```json
{
  "chatId": "uuid",
  "messageId": "uuid",
  "model": "gpt-5.6-sol",
  "modelProvider": "anthropic",
  "content": {
    "text": "Le big bang est la theorie...",
    "reasoning": "Je vais expliquer simplement...",
    "codeBlocks": [{"language": "python", "code": "def quicksort..."}],
    "javascriptBlocks": [],
    "functionCalls": [],
    "webSearchCalls": []
  },
  "downloadedImages": [
    {
      "filename": "chat_msg_img_20260706_171635.png",
      "localPath": "/home/user/.../image.png",
      "downloadUrl": "http://localhost:8765/images/chat_msg_img_20260706_171635.png",
      "sizeBytes": 948005
    }
  ],
  "tokenUsage": {
    "promptTokenCount": 100,
    "candidatesTokenCount": 200,
    "totalTokenCount": 300,
    "reasoningTokenCount": 50
  },
  "isFinished": true,
  "finishedReason": "completed"
}
```

---

## Guide pour les IA / Harness

Tu es une IA (OpenCode, Claude Code, Pi, Codex, Cursor...) et tu veux utiliser ce bridge ? Voici comment.

### Connexion au bridge

Le bridge expose une API HTTP locale. Pas besoin de SDK, juste `fetch()` ou `curl`.

```python
# Exemple Python pour ton harness
import requests

def chat(message, model="gpt-5.6-sol", stream=False):
    """Appelle France Student via le bridge local."""
    r = requests.post(
        "http://localhost:8765/v1/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": message}],
            "stream": stream,
        },
    )
    r.raise_for_status()
    return r.json()

# Utilisation
reponse = chat("Explique le paradoxe de Fermi en 3 phrases", model="claude-opus-5")
print(reponse["choices"][0]["message"]["content"])
print(f"Modele utilise: {reponse['model']}")
print(f"Tokens: {reponse['usage']['total_tokens']}")
```

```javascript
// Exemple JavaScript
async function chat(message, model = "gpt-5.6-sol", stream = false) {
  const res = await fetch("http://localhost:8765/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model,
      messages: [{ role: "user", content: message }],
      stream
    })
  });
  return res.json();
}
```

### Architecture cible

```
[Harnass IA (Pi/Codex/OpenCode)]
          |
          v
  [Bridge Service :8765]  ←  Ce projet
          |
          v
  [api.francestudent.ai]  ←  API officielle France Student
          |
          v
  [GPT | Claude]
```

### Parametres de `/chat/completions`

| Parametre | Type | Defaut | Description |
|-----------|------|--------|-------------|
| `message` | string | requis | Le prompt a envoyer |
| `agentId` | int | auto | ID France Student (`64`/`gpt-5.6-sol` par defaut) |
| `model` | string | - | Nom du modele (alternative a `agentId`) |
| `stream` | bool | true | `true`=SSE streaming, `false`=JSON |
| `images` | array | [] | UUIDs d'images uploadees |
| `files` | array | [] | IDs de fichiers uploades |
| `enableWebSearch` | bool | false | Activer la recherche web |

Pour `/v1/chat/completions`, utilise le format standard `model` + `messages`. Les parties `image_url` sont reelles : chaque URL ou data URL est telechargee, puis envoyee via `/files/upload` dans le champ `images` de France Student. Le texte reste intact et aucun placeholder `[IMAGE]` n'est substitue.

### Quotas et densite des messages

France Student publie **50 nouvelles conversations par jour** et **100 messages
de chat par heure**. Le pont s'y tient avec de la marge :

| Reglage | Defaut | Effet |
|---------|--------|-------|
| `FS_MAX_MESSAGES_PER_HOUR` | `60` | fenetre glissante ; une requete attend son tour |
| `FS_MAX_NEW_CHATS_PER_DAY` | `40` | une session OpenCode = une conversation France Student |
| `FS_QUOTA_WAIT_TIMEOUT` | `600` | secondes d'attente maxi pour un creneau libre |

Les requetes auxiliaires qui n'ont pas besoin du modele sont traitees
localement : le **titre de session** est produit par le pont, il ne coute donc
aucun message France Student. `GET /usage` expose l'etat des compteurs.

### Generation d'images

`POST /v1/images/generations` delegue chaque image au outil `image-generation` de France Student (`image_generation_call`), puis :

1. recupere l'UUID de l'image finale ;
2. la telecharge dans `storage/images/` ;
3. renvoie `http://localhost:8765/images/<fichier>.png` avec `response_format=url` ;
4. ou renvoie son contenu encode avec `response_format=b64_json`.

`model=dall-e-3`, `dall-e-2`, `gpt-image-1` et `gpt-image-1-mini` sont des alias de delegation. Le modele agent reel est configure par `FS_IMAGE_MODEL`/`FS_IMAGE_AGENT_ID` (`gpt-5.6-sol`/`64` par defaut). `n` est limite a 8. Les champs `size` et `quality` sont ajoutes a la consigne : France Student ne garantit pas une dimension ou une qualite de sortie exactement identiques au format OpenAI.

### Detection d'erreurs

Si `finishedReason` vaut `"error"`, le champ `errorMessage` contient le detail. Cela arrive souvent quand le modele est overload (503) ou indisponible.

```python
reponse = chat("Hello", model="gpt-5.6-sol")
if reponse["finishedReason"] == "error":
    print(f"Erreur: {reponse['errorMessage']}")
    # Reessaie avec un autre modele
    reponse = chat("Hello", model="claude-sonnet-5-5")
```

### Validation automatisee

```bash
# Tests unitaires locaux
python -m unittest discover -s tests -v

# Validation live complete: auth, modeles, chat streaming/non-streaming,
# vision URL/base64, generation et fichier local
python scripts/validate_bridge.py

# Ou valider un bridge deja lance
python scripts/validate_bridge.py --base-url http://localhost:8765
```

---

## Architecture du projet

```
france-student-bridge/
├── bridge_server.py     # Serveur Flask — point d'entree
├── agentic_bridge.py    # Boucle de conversation, outils, quotas, dedup
├── auth.py              # Session du navigateur ou cle API, refresh automatique
├── api_client.py        # Client HTTP pour l'API France Student
├── tool_bridge.py       # Correspondance outils France Student <-> outils OpenCode
├── rate_limiter.py      # Quotas glissants (messages/h, conversations/jour)
├── session_store.py     # Association session OpenCode <-> conversation FS
├── sse_parser.py        # Parsing du flux SSE temps reel
├── openai_adapter.py    # Conversion des reponses FS vers le format OpenAI
├── image_handler.py     # Vision upload + stockage des images generees
├── model_catalog.py     # Catalogue OpenAI + alias de modeles
├── config/config.py     # Configuration centralisee
├── .opencode/plugins/   # Plugin de session OpenCode
├── scripts/validate_bridge.py
├── scripts/export_opencode_config.py
├── scripts/fs_session_login.js
├── docs/                # Documentation de reference
├── tests/               # Tests unitaires
├── storage/images/      # Dossier de stockage des images
├── requirements.txt     # httpx, flask, aiofiles
├── run.sh               # Lancement Linux/Mac
├── run.bat              # Lancement Windows
└── .gitignore           # Protege les donnees sensibles
```

---

## Securite

Aucune donnee ne quitte ton ordinateur en dehors des appels vers France Student :

- L'authentification passe par la session de ton navigateur : le cookie vit dans `.fs-session.json`, sur ta machine, et n'est jamais journalise
- Une **Cle API officielle** peut etre utilisee a la place (`FS_AUTH_MODE=api_key`) des que ton compte y a acces
- Le dossier `storage/images/` est exclu du repo
- Toute connexion vers France Student se fait en HTTPS
- Les images entrantes sont limitees par `MAX_UPLOAD_BYTES` et `MAX_IMAGE_DOWNLOAD_BYTES`
- Le pont reste sous les quotas publies et ne relance jamais une requete mutante dont le resultat serait ambigu

---

## Avertissement

> Ce projet s'appuie sur l'API **officielle** de France Student, dont la
> specification est publique. L'authentification utilise la session de ton
> propre compte, ou une Cle API si ton compte y a acces. Il peut cesser de
> fonctionner si France Student modifie son API.
>
> Ce projet n'est **pas affilie a France Student**. C'est un outil communautaire open-source. Utilise-le de facon raisonnable — ne spamme pas l'API, ne contourne pas les limites de rate limiting.
>
> Si le bridge ne fonctionne plus, ouvre une **issue** sur ce repo, on corrigera.

---

## Licence

MIT — fais-en ce que tu veux. Un petit mot sur le repo fait toujours plaisir.

<p align="center">
  <br>
  <b>Si ce projet t'est utile, laisse une etoile sur GitHub.</b>
  <br>
  <a href="https://github.com/jellay-dj/francestudent-link-opencode">
    <img src="https://img.shields.io/github/stars/jellay-dj/francestudent-link-opencode?style=social" />
  </a>
</p>
