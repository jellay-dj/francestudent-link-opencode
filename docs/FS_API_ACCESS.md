# France Student : accès à l'API

## Référence contractuelle

La documentation technique officielle de France Student est **publique** et
n'exige aucune authentification :

- Spécification OpenAPI : <https://api.francestudent.ai/v3/api-docs>
  (copie locale dans [`docs/francestudent-openapi.json`](francestudent-openapi.json))
- Interface Swagger : <https://api.francestudent.ai/swagger-ui/index.html>
- Hôte de l'API : `https://api.francestudent.ai`
- Front et authentification : `https://ia.francestudent.org`

Les CGU de l'Offre IA version 2.0 (avril 2026), Livre V « Accès
programmatique (API) », restent la référence juridique :
<https://cdn.francestudent.org/documents/pdf/2026_cgu_ia_ffs.pdf>.

## Les deux mécanismes d'authentification

### 1. Clé API officielle (`FS_AUTH_MODE=api_key`)

Les CGU (articles 30.2, 31.1) prévoient un **Compte API distinct** du Compte
Utilisateur et des **Clés API**. L'endpoint documenté est :

- `GET /user/@me/api-key` : consulter sa clé
- `POST /user/@me/api-key` : générer sa clé
- `DELETE /user/@me/api-key` : révoquer sa clé

La clé est envoyée dans l'en-tête `authorization` (schéma de sécurité
`sessionToken` de la spécification).

**État vérifié le 16/11/2026 : cet endpoint n'est pas ouvert au compte
utilisé.** La réponse est explicite :

```
403 Forbidden
"Missing required unleash toggle. Expected one of: 2026_10_api_keys"
```

La fonctionnalité est derrière un drapeau de déploiement que ce compte
n'a pas. Contourner ce drapeau n'est ni possible ni souhaitable : le pont
attend simplement qu'un Compte API soit accordé.

Tant que ce n'est pas le cas, le pont fonctionne en mode `session`.

### 2. Session du navigateur (`FS_AUTH_MODE=session`, mode par défaut)

C'est l'authentification que l'application France Student elle-même utilise.
Elle a été relevée sur l'application réelle et vérifiée en direct.

```
GET https://ia.francestudent.org/api/auth/api-token
```

En-têtes obligatoires :

| En-tête | Valeur |
| --- | --- |
| `francestudent-client-platform` | `web_fs_ai` |
| `francestudent-client-version` | `ac0e023` |
| `francestudent-device-id` | UUID de l'appareil |
| `Referer` | `https://ia.francestudent.org/` |
| `Origin` | `https://ia.francestudent.org` |

plus le cookie de session du navigateur.

Réponse :

```json
{"accessToken": "<JWT>", "expiresAt": 1794777983, "expiresIn": 300, "tokenType": "Bearer"}
```

Points importants, tous vérifiés :

- Sans les trois en-têtes `francestudent-*`, la réponse est
  `400 {"error":"Invalid client metadata"}`.
- Sans `Referer`, le CDN répond `403 {"error":"request_blocked"}`. C'est la
  protection anti-robot, pas l'authentification.
- Le jeton dure **5 minutes** ; le cookie de session dure bien plus longtemps.
  Le bridge échange donc le cookie contre un jeton, puis renouvelle le jeton
  automatiquement avant expiration.
- Le jeton porte `aud: "spring-api"` et l'adresse IP de l	client. Le bridge
  tourne sur la même machine, donc la même IP.
- Toutes les requêtes API sont ensuite envoyées à
  `https://api.francestudent.ai` avec
  `Authorization: Bearer <jeton>`.

### Comment obtenir le cookie de session

`scripts/fs_session_login.js` ouvre Chrome avec un profil dédié et attend que
**l'utilisateur se connecte lui-même**. Aucun mot de passe n'est lu, saisi ni
automatisé : le formulaire SSO n'est jamais rempli par un script. Le script
écrit ensuite `.fs-session.json` (ignoré par Git).

Le fichier contient un cookie de session : c'est un secret. Il ne doit être ni
affiché, ni copié dans une configuration, ni commité.

## Limites publiées et observées

| Limite | Valeur | Constatée le |
| --- | --- | --- |
| Nouvelles conversations par jour | 50 | 16/11/2026, via `429 Daily new chat limit reached (50 per day)` |
| Messages de chat par heure | 100 (CGU, annexe 1) | — |
| Budget de chat | mensuel, visible via `GET /user/usage` | 16/11/2026 |

Le pont reste volontairement **en dessous** de ces limites :

- `FS_MAX_MESSAGES_PER_HOUR` (60 par défaut) : fenêtre glissante, une
  requête attend son tour au lieu d'être abandonnée.
- `FS_MAX_NEW_CHATS_PER_DAY` (40 par défaut) : une nouvelle session OpenCode
  consomme une conversation France Student.
- Le titre de session est produit **localement** par le pont : il ne coûte
  aucun message France Student.
- `GET /usage` du pont expose l'état de ces compteurs.

Un `429` reçu de France Student est remonté tel quel à OpenCode, avec le
message de France Student. Un quota atteint côté pont renvoie `429`
`bridge_quota_exhausted`.

## Ce qu'il ne faut pas faire

- Ne pas créer de comptes supplémentaires pour contourner une limite ou un
  refus d'authentification.
- Ne pas automatiser le formulaire SSO ni resubmettre des identifiants de
  compte web pour obtenir un accès API.
- Ne pas deviner un endpoint, un en-tête ou un format de clé : la
  spécification publique est la référence.
- Ne pas multiplier les conversations pour obtenir un résultat : une
  conversation par session OpenCode, réutilisée pour tous les tours.
