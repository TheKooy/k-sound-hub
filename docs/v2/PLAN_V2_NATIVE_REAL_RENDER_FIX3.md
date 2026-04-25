# K-Sound Hub V2 - Native Real Render Fix 3

Objectif : polir les petits crépitements résiduels en écoute normale sans changer l'architecture.

Changements :
- augmente la latence des captures `parec` à 60 ms
- augmente la latence de playback `pacat` à 120 ms
- augmente `process-time-msec` à 40 ms
- ajoute une marge fixe (`mix_headroom = 0.72`) dans le mix natif
- ajoute une ligne de log de démarrage avec ces paramètres

Ce patch ne change pas l'UI ni la logique de contrôle. Il cible uniquement la couche I/O helper autour du moteur natif.
