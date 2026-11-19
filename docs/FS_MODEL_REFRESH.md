# Mettre à jour les modèles France Student dans OpenCode

Cette procédure garde le sélecteur OpenCode aligné sur le catalogue renvoyé par l'API France Student. Elle ne déduit jamais un identifiant à partir d'un nom affiché.

La spécification de l'API est publique : <https://api.francestudent.ai/v3/api-docs>. Avant un appel live, lire [`FS_API_ACCESS.md`](FS_API_ACCESS.md) : le compte utilisateur web et le Compte API sont distincts selon les CGU FS ; ne pas lancer le rafraîchissement avec un parcours qui automatise le formulaire SSO.

## Procédure

1. Lancer le bridge avec `run.bat`, puis vérifier `http://127.0.0.1:8765/health`. La réponse doit indiquer `authenticated: true` et `authMode: session` (ou `api_key`).
2. Dans PowerShell, aller explicitement à la racine du dépôt avant de lancer le script. Le chemin relatif ne fonctionne pas si PowerShell est resté dans `C:\Users\yannl` :

   ```powershell
   $bridge = Join-Path $env:USERPROFILE 'Documents\Jules\Opencode bridge\france-student-bridge'
   Set-Location -LiteralPath $bridge
   python .\scripts\export_opencode_config.py --output .\opencode.france-student.generated.json
   ```

   Le script demande `GET /v1/models?refresh=true`. Le bridge force alors un rafraîchissement depuis FS. En cas d'échec réseau ou d'authentification, il renvoie une erreur et le script ne produit pas une nouvelle liste à partir d'un ancien cache.

3. Examiner `providers.france-student.models` dans le fichier généré. Les clés et `modelID` reprennent les `id` canoniques de `/v1/models`; le libellé vient de `fs_name`. Le champ `fs_agent_id` n'est pas utilisé comme identifiant du sélecteur.
4. Examiner le diff. Pour mettre à jour le fichier global OpenCode Windows déjà présent sur cette machine, toujours depuis la racine du dépôt, lancer ensuite :

   ```powershell
   python .\scripts\export_opencode_config.py --apply-config (Join-Path $env:USERPROFILE '.config\opencode\opencode.json')
   ```

   Le script refait le rafraîchissement puis remplace uniquement `providers.france-student`, ajoute le plugin de session s'il manque et préserve les autres providers, plugins, le modèle par défaut et les réglages MCP. Il refuse d'écraser une configuration invalide ou commentée qu'il ne sait pas fusionner. Pour un autre chemin, passer ce chemin à `--apply-config`.
5. Cette opération retire de la liste France Student les IDs qui ne figurent plus dans le catalogue actif, et ajoute les nouveaux. Vérifier le diff et la validité JSON/JSONC, puis recharger OpenCode et ouvrir `/models` pour vérifier les entrées `france-student/<id>`. Si `opencode` n'est pas dans le `PATH`, appeler directement le CLI installé avec l'application :

   ```powershell
   $openCodeCli = Join-Path $env:LOCALAPPDATA 'Programs\ai.opencode.desktop\resources\opencode-cli.exe'
   if (-not (Test-Path -LiteralPath $openCodeCli)) { throw "CLI OpenCode introuvable : $openCodeCli" }
   & $openCodeCli reload
   & $openCodeCli models
   ```

Le fichier généré est ignoré par Git, car il contient un chemin absolu propre à cette installation. Il ne contient ni identifiant de compte ni jeton. Le script ne sauvegarde jamais `.env`, `.fs-session.json` ou les cookies.

## Requêtes longues

Les modèles FS peuvent attendre longtemps avant leur première réponse et le bridge ajoute une étape réseau. La configuration générée fixe donc une limite de 20 minutes avant les en-têtes, 20 minutes entre les fragments et 30 minutes pour la requête OpenCode complète. Côté bridge, une lecture SSE peut attendre 20 minutes entre fragments et une conversation est plafonnée à 30 minutes. Ces délais restent finis pour permettre un arrêt propre.

Les valeurs bridge peuvent être ajustées dans `.env` avec `FS_SSE_CONNECT_TIMEOUT`, `FS_SSE_READ_TIMEOUT`, `FS_SSE_WRITE_TIMEOUT`, `FS_SSE_POOL_TIMEOUT`, `FS_REQUEST_TIMEOUT` et `FS_CHAT_TOTAL_TIMEOUT`. Garder `FS_CHAT_TOTAL_TIMEOUT` supérieur au temps de lecture SSE souhaité. Après modification, redémarrer `run.bat` et recharger OpenCode.

## Règles de maintenance

- Ne pas recopier les anciens IDs documentés dans le README comme s'ils étaient actuels. Le catalogue FS peut changer.
- Ne pas confondre `id` (nom canonique utilisé dans le sélecteur) avec `fs_agent_id` (ID transmis à l'API FS) ou `fs_name` (nom d'affichage).
- Si le catalogue actif ne contient pas `GPT 6 Astra` ou `Fable 5.2`, ne pas inventer leur ID : signaler les modèles exacts renvoyés par FS et demander à l'utilisateur si un autre choix est souhaité.
- Conserver `@opencode/ai/providers/openai-compatible`, `http://127.0.0.1:8765/v1` et le plugin de session. Ils relient le sélecteur à l'API locale, ajoutent l'identifiant de session OpenCode à chaque requête et désactivent les relances automatiques pour éviter les doubles envois vers FS.
- Le bridge annonce la prise en charge des outils au format OpenAI et valide les appels selon les schémas reçus d'OpenCode. La prise en charge réelle de chaque modèle FS reste à vérifier par un échange et un appel d'outil contrôlé.
- Ne jamais inclure `.env`, `store.json`, les jetons ou des cookies dans une configuration, une sortie de commande, un commit ou un rapport.

## Sources techniques

- Catalogue du bridge : `GET /v1/models` et `GET /v1/models?refresh=true`.
- Configuration de fournisseur compatible OpenAI : https://opencode.ai/docs/providers/
- Sélection des modèles dans OpenCode : https://opencode.ai/docs/models/
- Chargement des plugins locaux : https://opencode.ai/docs/build/plugins/
