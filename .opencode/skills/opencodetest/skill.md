# Skill : opencodetest

Ce skill permet de tester rapidement la connexion entre OpenCode, le pont
France Student et le modèle France Student, en invoquant l'agent `@test`.

## Utilisation

Dans OpenCode, invoquez l'agent :

```
@test
```

Ou avec un message explicite :

```
@test envoie une requete de test a France Student
```

## Ce qui se passe

L'agent `@test` est géré directement par le pont France Student (pas par un
modele). Il envoie le message suivant a France Student :

```
$opencodetest
```

Et revoie la reponse du modele, ainsi que le nom du modele utilise et le
statut de fin.

## Exemple de sortie

```
Test de connexion a France Student reussi.
Modele utilise : gpt-6-astra
Statut : stop

Reponse du modele :
Bien recu ! Je suis opérationnel.
```

## Dépannage

Si vous recevez une erreur :

1. Verifiez que le pont est lance (`python bridge_server.py`)
2. Verifiez que `http://127.0.0.1:8765/health` repond `authenticated: true`
3. Verifiez que votre session France Student est exportee
   (`scripts/fs_session_login.js`)
4. Si un modele est surcharge, le pont bascule automatiquement sur un autre
   (fallback : Astra → Fable → Sonnet → Terra)

## Fichiers lies

- `scripts/majfs.py` : rafraichit le catalogue des modèles France Student
- `agentic_bridge.py` : logique du pont, dont l'agent `@test`
- `fs_actions.py` : fonction `test_connection` qui envoie `$opencodetest`