# Passation : pont OpenCode ↔ France Student

État au 16 novembre 2026. Cette note prépare la reprise du travail par un
autre agent. Elle ne contient aucun identifiant, cookie, jeton, mot de passe
ni contenu de conversation.

## Objectif

Permettre à OpenCode, sur Windows, d'utiliser les modèles France Student du
compte de l'utilisateur tout en laissant OpenCode gérer l'interface et
l'exécution locale des outils. Le pont maintient une conversation France
Student par session OpenCode et renvoie au modèle les résultats des outils.

## À lire d'abord

1. [`AGENTS.md`](../AGENTS.md) : règles permanentes de maintenance et de sécurité.
2. [`FS_API_ACCESS.md`](FS_API_ACCESS.md) : authentification et quotas vérifiés.
3. [`FS_CLIENT_TOOLS.md`](FS_CLIENT_TOOLS.md) : le protocole d'outils natifs.
4. [`FS_MODEL_REFRESH.md`](FS_MODEL_REFRESH.md) : protocole de mise à jour du sélecteur de modèles.
5. `README.md` : fonctionnement et commandes Windows documentées.

## Ce qui fonctionne aujourd'hui

Vérifié en direct le 16/11/2026, avec le vrai OpenCode 2.3.0 et l'API
France Student :

| Fonctionnalité | État |
| --- | --- |
| Authentification par session du navigateur | opérationnelle |
| Récupération du catalogue des modèles | opérationnelle (12 agents actifs) |
| `/v1/models` compatible OpenAI | opérationnel |
| Conversation simple | opérationnelle |
| Appels d'outils natifs (`read`, `write`, `edit`, `shell`, `grep`) | opérationnels |
| Continuité de session (une conversation FS par session OpenCode) | opérationnelle |
| Titre de session produit localement (0 message FS) | opérationnel |
| Conversations créées dans le projet France Student « Bridge » | opérationnel |
| Limitation de débit côté pont (60 messages/h, 40 conversations/jour) | opérationnelle |

Exemple réel d'une session OpenCode pilotée par `gpt-6-astra` :

```
> build · gpt-6-astra
→ Read NOTES.md
→ $ echo bonjour-depuis-france-student
bonjour-depuis-france-student
→ Patch 1 file
The planned budget is €120, according to NOTES.md (line 4).
```

## Découvertes qui ont changé la conception

1. **La documentation de l'API France Student est publique.**
   <https://api.francestudent.ai/v3/api-docs> (111 endpoints, copie locale
   dans `docs/francestudent-openapi.json`). L'affirmation précédente selon
   laquelle `ia.francestudent.org/api/docs` redirigeait vers `/login` ne
   vaut que pour ce chemin : l'hôte documenté est `api.francestudent.ai`.

2. **L'API officielle ne demande pas les identifiants web.** Elle attend une
   clé API (`/user/@me/api-key`), derrière un drapeau de déploiement
   (`2026_10_api_keys`) qui n'est pas actif sur ce compte : `403`. Le pont
   utilise donc la session du navigateur, échangée contre un jeton via
   `/api/auth/api-token`, comme le fait l'application France Student.

3. **France Student a un protocole d'outils clients natifs.** Une conversation
   déclare `clientTools`, le modèle émet un `function_call` avec un
   `call_id`, et le client répond par `toolResults`. C'est ce protocole que le
   pont utilise, et non l'analyse de balises `<function_call>`.

4. **Les modèles refusent le protocole « maison ».** Envoyé sous la forme
   « tu es le modèle appelé par OpenCode via un pont », le modèle répond
   qu'il ne peut pas « servir de moteur à un outil ou à un agent externe ».
   Le message envoyé au modèle est donc resté plat, et le prompt système
   d'OpenCode n'est pas transmis (`FS_FORWARD_SYSTEM_PROMPT`).

5. **Les quotas sont réels.** 50 nouvelles conversations par jour, 100
   messages par heure. Le pont se tient en dessous et les titre de session
   sont produits localement.

## Points de vigilance

- Le refus du point 4 n'est pas entièrement prévisible : selon le modèle et
  la formulation, certains modèles refusent encore une demande d'action. Le
  pont renvoie alors la réponse du modèle telle quelle.
- La clé API officielle n'est pas encore disponible sur ce compte. Le jour où
  elle l'est, `FS_AUTH_MODE=api_key` et `FS_API_KEY` suffisent : le reste du
  pont est inchangé.
- Les schémas d'arguments des outils clients ne sont pas publiés : ils ont
  été relevés en direct et sont documentés dans `FS_CLIENT_TOOLS.md`. Une
  évolution de France Student les changerait.
- OpenCode change ses noms d'outils (`bash` → `shell`, `edit` → `patch` selon
  le modèle). La correspondance est résolue à chaque requête à partir des
  schémas reçus, mais de nouveaux outils-side peuvent apparaître.
- Les conversations du pont vivent dans le projet France Student « Bridge »
  (`FS_PROJECT_ID`). Les conversations créées avant ce réglage restent dans
  l'onglet principal.

## Architecture locale en place

- OpenCode utilise un fournisseur compatible OpenAI pointant vers le bridge
  local `http://127.0.0.1:8765/v1`.
- Le plugin `.opencode/plugins/france-student-session/index.ts` ajoute
  `x-opencode-session-id`, `x-opencode-request-kind` et
  `x-opencode-directory` à chaque appel, et désactive les relances de
  transport pour les requêtes FS avec effets de bord.
- `bridge_server.py` expose les endpoints locaux ; `/v1/chat/completions`
  délègue à `agentic_bridge.py`.
- `agentic_bridge.py` orchestre : catalogue, conversation, boucle d'outils,
  déduplication, quotas.
- `tool_bridge.py` résout la correspondance entre les outils clients France
  Student et les outils OpenCode à partir des schémas de la requête.
- `rate_limiter.py` applique les quotas côté pont.
- `session_store.py` conserve dans SQLite l'association `session OpenCode →
  conversation FS`, l'état de la requête, les empreintes de déduplication et
  les appels d'outils en attente.
- `scripts/export_opencode_config.py` construit la liste OpenCode à partir du
  catalogue du bridge et ne remplace que le provider France Student.

## Changements locaux à préserver

Le dépôt local est `C:\Users\yannl\Documents\Jules\Opencode bridge\france-student-bridge`,
branche `master`. Ne pas exécuter `git reset`, `git clean`, ni restaurer en
bloc les fichiers : examiner et préserver chaque changement.

Fichiers ajoutés ou modifiés pendant ce travail : `agentic_bridge.py`,
`auth.py`, `api_client.py`, `bridge_server.py`, `config/config.py`,
`openai_adapter.py`, `sse_parser.py`, `tool_loop.py`, `tool_bridge.py`
(nouveau), `rate_limiter.py` (nouveau), `session_store.py`,
`scripts/fs_session_login.js` (nouveau),
`scripts/export_opencode_config.py`, `.opencode/plugins/france-student-session/index.ts`,
`run.bat`, `.env.example`, `.gitignore`, `README.md`, `AGENTS.md`, `docs/`
(entièrement réécrit), `tests/` (49 tests).

## Vérifications réalisées

- `python -m unittest discover -s tests` : **49 tests réussis**.
- `python -m compileall -q .` : à relancer après les derniers changements.
- Session OpenCode réelle avec `gpt-6-astra` : lecture de fichier,
  commande shell, écriture de fichier, modification de fichier et recherche
  dans le projet, tous exécutés par OpenCode via le pont.
- Catalogue live : 12 agents actifs, identiques à la configuration OpenCode
  installée.

## Étapes de reprise

1. Relancer `python -m compileall -q .` et la suite de tests.
2. Vérifier `http://127.0.0.1:8765/health` : `authenticated: true`,
   `authMode: session`, et les compteurs de quota.
3. Si la session a expiré : `node scripts\fs_session_login.js`, se connecter
   dans la fenêtre Chrome, puis redémarrer le bridge.
4. Pour ajouter ou rafraîchir des modèles : suivre
   [`FS_MODEL_REFRESH.md`](FS_MODEL_REFRESH.md) et montrer le diff du
   provider avant application.
5. Si le compte obtient une clé API officielle : `FS_AUTH_MODE=api_key` et
   `FS_API_KEY`, puis vérifier que `/health` renvoie `authMode: api_key`.
6. Pour les tests live : un échange simple, un appel d'outil, une nouvelle
   session, la continuité, deux sessions concurrentes, un refus de
   permission, une limite de quota. Une action non confirmée ne doit jamais
   être rapportée comme réussie.
