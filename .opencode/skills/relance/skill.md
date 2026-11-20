# Skill : relance

Ce skill permet de relancer le pont France Student et OpenCode en invoquant
l'agent `@relance`.

## Utilisation

Dans OpenCode, invoquez l'agent :

```
@relance
```

Ou avec un message explicite :

```
@relance relance le pont et OpenCode
```

## Ce qui se passe

L'agent `@relance` est géré directement par le pont France Student (pas par un
modèle). Il ne redémarre pas le pont automatiquement (le pont ne peut pas se
relancer tout seul : il s'arreterait sans pouvoir se relancer), mais il
retourne les commandes exactes a executer pour :

1. Arreter le pont (bridge)
2. Le relancer
3. Verifier qu'il est en ligne
4. Recharger OpenCode
5. Recharger le catalogue des modeles
6. Tester avec @test

## Exemple de sortie

```
Relance du pont France Student et d'OpenCode
============================================

1. Arreter le pont (bridge) :
   - Fenetre console du pont : Ctrl+C
   - Ou depuis PowerShell :
       Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
         Where-Object { $_.CommandLine -match 'bridge_server' } |
         ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

2. Relancer le pont :
   - Windows : double-cliquez sur run.bat
   - Ou : python bridge_server.py
   ...

3. Verifier que le pont est en ligne :
   curl http://localhost:8765/health
   ...

4. Recharger OpenCode :
   - Dans OpenCode : Ctrl+Shift+P -> "Reload Window"
   ...

5. Recharger le catalogue des modeles :
   - Invoquez @majfs dans OpenCode
   ...

6. Tester :
   - Invoquez @test dans OpenCode
   ...
```

## Dépannage

Si le probleme persiste après relance :

- Verifiez que votre session France Student est encore valide
  (`scripts/fs_session_login.js`)
- Verifiez que le pont est bien sur le port 8765
  (`http://127.0.0.1:8765/health`)
- Si un modele est surcharge, le pont bascule automatiquement sur un autre
  (fallback : Astra → Fable → Sonnet → Terra)

## Fichiers lies

- `fs_actions.py` : fonction `get_relance_instructions`
- `bridge_server.py` : serveur Flask, gestion de l'agent `@relance`
- `config/config.py` : variable `FS_RELANCE_AGENT` (défaut: relance)
- `scripts/majfs.py` : rafraîchit le catalogue des modèles France Student
- `scripts/fs_session_login.js` : exporte votre session navigateur