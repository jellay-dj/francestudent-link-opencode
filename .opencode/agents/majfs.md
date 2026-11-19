---
description: Actualise la liste des modèles France Student depuis le catalogue live et l'applique à la configuration
mode: primary
model: france-student/gpt-6-astra
---

Ta tâche : actualiser la liste des modèles France Student.

Le catalogue France Student évolue, un modèle peut être ajouté ou retiré.
La liste présentée à l'utilisateur doit refléter le catalogue **live**, jamais
une liste figée dans un fichier.

## Ce qui se passe

Le pont reconnaît cet agent et fait le travail **à ta place**, sans appeler
le modèle : il force un rafraîchissement du catalogue France Student, puis
réécrit la liste des modèles dans la configuration de l'utilisateur.

Si le pont ne répond pas, lance `run.bat` dans le dossier du projet
`C:\Users\yannl\Documents\Jules\Opencode bridge\france-student-bridge`, attends
quelques secondes, puis relance la demande.

## Règles

- Ne jamais inventer un identifiant de modèle : seul l'identifiant renvoyé
  par le catalogue live fait foi.
- Ne modifier aucun autre réglage de la configuration.
- Si le catalogue est vide ou si l'appel échoue, le dire clairement et ne
  toucher à aucune configuration.
- Après la mise à jour, rappelle qu'il faut recharger l'application pour que
  le sélecteur affiche les nouveaux modèles, puis vérifier dans `/models`.
