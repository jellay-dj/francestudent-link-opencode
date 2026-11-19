# Les outils clients natifs de France Student

France Student n'expose pas ses outils à OpenCode : il les expose à **son
propre client**. Une conversation déclare la liste des outils que le client
sait exécuter, le modèle demande ensuite ces outils nativement, et le client
renvoie les résultats.

C'est le protocole que le bridge utilise. Il est documenté par France Student
dans la spécification OpenAPI publique, et les schémas d'arguments ont été
observés sur l'API en direct.

Sources :

- Spécification publique : <https://api.francestudent.ai/v3/api-docs>
  (copie locale : [`francestudent-openapi.json`](francestudent-openapi.json))
- `ChatCreateDto.clientTools`, `ChatCreateDto.projectId`
- `ChatToolCallDto`, `ChatToolResultInputDto`

## Le protocole

1. Le client ouvre une conversation et déclare `clientTools` :

   ```json
   POST https://api.francestudent.ai/chats/stream
   {
     "agentId": -1004,
     "initialContent": "Dossier de travail : C:/projet\n\nLis le fichier NOTES.md.",
     "clientTools": ["list_directory", "read_file", "run_command"],
     "enableWebSearch": false
   }
   ```

2. Le modèle répond avec un élément `function_call` :

   ```json
   {
     "type": "function_call",
     "id": "fc_0dfe…",
     "call_id": "call_j5I2nOHoeaFnzibQ3kfMhBK4",
     "name": "list_directory",
     "arguments": "{\"path\":\".\",\"depth\":1}",
     "status": "completed"
   }
   ```

   Le `call_id` est l'identifiant à réutiliser pour répondre.

3. Le client exécute l'outil et renvoie le résultat dans la **même**
   conversation :

   ```json
   POST https://api.francestudent.ai/chats/{chatId}
   {
     "content": "",
     "toolResults": [
       {"callId": "call_j5I2nOHoeaFnzibQ3kfMhBK4", "output": "NOTES.md\nREADME.md\n", "isError": false}
     ],
     "clientTools": ["list_directory", "read_file", "run_command"]
   }
   ```

4. Le modèle poursuit avec le résultat.

## Les six outils clients

Les noms et les arguments sont fixes côté France Student. Ils ont été relevés
sur l'API en direct en demandant au modèle chaque outil.

| Outil France Student | Arguments | Effet |
| --- | --- | --- |
| `list_directory` | `path` (string), `depth` (integer) | liste un répertoire |
| `read_file` | `path` (string) | lit un fichier |
| `search_files` | `query` (string), `path` (string), `max_results` (integer) | recherche dans le contenu |
| `edit_file` | `path`, `old_text`, `new_text` (strings), `replace_all` (boolean) | remplace un texte dans un fichier |
| `write_file` | `path`, `content` (strings) | crée ou remplace un fichier |
| `run_command` | `command` (string), `cwd` (string), `timeout_seconds` (integer) | exécute une commande |

## Correspondance avec les outils OpenCode

OpenCode ne propose pas les mêmes noms, ni les mêmes schémas, et ils changent
d'une version à l'autre. La correspondance est donc **résolue à chaque
requête** à partir des schémas réellement reçus (`tool_bridge.py`), jamais
supposée.

| France Student | OpenCode (v2) | Ce qui est traduit |
| --- | --- | --- |
| `read_file` | `read` | `path` ; chemin relatif résolu contre le dossier de travail |
| `list_directory` | `read` sur un répertoire | `path` |
| `search_files` | `grep` | `query` → `pattern`, `path`, `max_results` → `limit` |
| `run_command` | `shell` | `command`, `cwd` → `workdir`, `timeout_seconds` → `timeout` (ms) |
| `edit_file` | `edit`, sinon `patch` | `old_text` → `oldString`, `new_text` → `newString` |
| `write_file` | `write`, sinon `patch` | `path`, `content` |

OpenCode n'expose `patch` que pour les modèles GPT et `edit`/`write` pour les
autres. Quand seul `patch` est disponible, le bridge fabrique un document de
patch :

```
*** Begin Patch
*** Update File: NOTES.md
@@
-Le budget prevu est de 120 euros.
+Le budget prevu est de 250 euros.
*** End Patch
```

France Student remplace un **fragment** de texte pendant qu'OpenCode applique
des patchs **par ligne**. Le bridge lit donc le fichier concerné pour
transformer le remplacement en lignes, sans quoi la vérification du patch
échoue.

Un outil OpenCode sans équivalent France Student (`question`, `webfetch`,
`websearch`, `skill`, `subagent`, `glob`, `execute`) n'est simplement pas
déclaré : le modèle ne demandera jamais un outil que le bridge ne peut pas
exécuter.

## Pourquoi ne pas passer par un protocole « maison »

Une première version du bridge demandait au modèle d'écrire des balises
`<function_call>` dans sa réponse et les analysait ensuite. **Les modèles
France Student refusent cette forme** : ils répondent alors qu'ils ne peuvent
pas « servir de moteur à un outil ou à un agent externe ».

Leurs mots exacts, relevés sur `gpt-6-astra` :

> Le chat France Student ne peut pas servir de moteur à un outil ou à un agent
> externe ; collez ici le contenu de NOTES.md et je vous indiquerai le budget.

Le refus dépendait du texte envoyé au modèle : un cadrage de type « tu es le
modèle appelé par OpenCode via un pont » ou l'injection d'un catalogue
d'outils en texte suffisaient à le déclencher. Le protocole natif, lui, n'est
pas refusé : c'est le mécanisme que France Student a prévu pour son propre
client.

Conséquence retenue dans le bridge : le message envoyé au modèle reste **plat**
(le dossier de travail, puis la demande), et le prompt système d'OpenCode
n'est **pas** transmis. `FS_FORWARD_SYSTEM_PROMPT=true` permet de le
transmettre si un modèle précis en a besoin, au risque de déclencher de
nouveau le refus.
