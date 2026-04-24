# K-Sound Hub V2 — final playback render tranche

Objectif : remplacer la famille `filter-chain` comme coeur playback par un moteur de mixage final contrôlé par K-Sound Hub.

## Fonctionnalités conservées

- `ALL / GAME / CHAT / MEDIA / MORE` restent les sinks visibles côté applis.
- `ALL` reste le point d'entrée par défaut.
- Une app peut être déplacée entre canaux.
- Volume/mute par canal.
- EQ différent par canal.
- Périphérique de sortie par canal.
- Plusieurs canaux peuvent viser ANPW ou S/PDIF en même temps.

## Changement interne

Avant :

```text
canal -> pipewire filter-chain -> périphérique physique
```

Maintenant :

```text
canal.monitor -> mixer V2 Python -> EQ par canal -> mix par périphérique -> 1 pacat par périphérique
```

Cette tranche ne cherche plus à réduire/patcher `filter-chain` : elle remplace le coeur playback par un moteur de mixage centralisé.

## Hors scope

- Refonte micro/retour.
- UI/perf.
- Publication GitHub.

## Critère de test principal

Avec plusieurs apps sur plusieurs canaux vers ANPW, le processus audio devrait ressembler à :

- plus de `pipewire -c filter-chain.conf` pour le playback V2
- un process mixer `v2_final_mixer`
- des captures `parec` par canal actif
- un rendu `pacat` unique vers ANPW

