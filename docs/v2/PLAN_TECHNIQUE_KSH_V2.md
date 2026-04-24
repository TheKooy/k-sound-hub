# K-Sound Hub V2 — Plan technique

## 1. Objectif

Construire **K-Sound Hub V2** dans le **même repo**, sans casser la version stable actuelle, en gardant les fonctionnalités visibles suivantes :

- canaux `ALL / GAME / CHAT / MEDIA / MORE`
- `ALL` comme canal d’entrée par défaut
- déplacement d’une app d’un canal à un autre
- volume par canal
- mute par canal
- EQ par canal
- choix du périphérique de sortie par canal
- overlay
- meters
- persistance des settings
- redémarrage propre et rollback simple

La V2 doit viser une base **plus robuste** que la topologie actuelle qui envoie plusieurs chaînes playback traitées directement vers la même sortie physique.

---

## 2. Constat sur l’architecture actuelle

Aujourd’hui, le chemin playback ressemble globalement à ceci :

```text
Apps
  -> sinks logiques (all / game / chat / media / more)
  -> 1 process EQ séparé par canal
  -> sortie physique directe
```

Exemple :

```text
media -> EQ media -> ANPW
game  -> EQ game  -> ANPW
chat  -> EQ chat  -> ANPW
```

Cette topologie garde bien les features, mais elle a deux points faibles :

1. plusieurs clients/chaînes traitées peuvent frapper le même périphérique physique en parallèle
2. le périphérique final reçoit plusieurs playback chains indépendantes au lieu d’un bus final plus propre

---

## 3. Architecture cible V2

## 3.1 Vue d’ensemble

```text
Applications
  -> channels visibles : ALL / GAME / CHAT / MEDIA / MORE
  -> traitement par canal :
       - volume
       - mute
       - EQ
       - meter
  -> bus interne du périphérique choisi
  -> rendu final par périphérique actif
  -> sortie physique
```

## 3.2 Schéma complet

```text
                      ┌──────────────────────────────┐
                      │         Applications         │
                      │ Spotify / Game / Discord ...│
                      └──────────────────────────────┘
                                      │
                                      ▼
                    ┌────────────────────────────────────┐
                    │  Channels visibles pour les apps   │
                    │  ALL / GAME / CHAT / MEDIA / MORE  │
                    └────────────────────────────────────┘
                                      │
                                      ▼
                    ┌────────────────────────────────────┐
                    │      Traitement par canal          │
                    │                                    │
                    │ ALL   -> vol / mute / EQ / meter   │
                    │ GAME  -> vol / mute / EQ / meter   │
                    │ CHAT  -> vol / mute / EQ / meter   │
                    │ MEDIA -> vol / mute / EQ / meter   │
                    │ MORE  -> vol / mute / EQ / meter   │
                    └────────────────────────────────────┘
                         │               │              │
                         ▼               ▼              ▼
              ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
              │ Device bus A   │ │ Device bus B   │ │ Device bus C   │
              │ Headset bus    │ │ SPDIF bus      │ │ Speakers bus   │
              └────────────────┘ └────────────────┘ └────────────────┘
                         │               │              │
                         ▼               ▼              ▼
              ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
              │ ANPW headset   │ │ SPDIF output   │ │ Speakers / HP  │
              └────────────────┘ └────────────────┘ └────────────────┘
```

---

## 4. Règles fonctionnelles à préserver

## 4.1 Entrée par défaut

- le sink par défaut système reste `ALL`
- toute nouvelle app tombe d’abord sur `ALL`
- K-Sound Hub peut ensuite laisser l’app sur `ALL` ou la déplacer sur un autre canal

## 4.2 Déplacement d’app

Exemple :

```text
Spotify démarre sur ALL
Puis K-Sound Hub le déplace sur MEDIA
```

Après déplacement, Spotify doit utiliser :

- volume MEDIA
- mute MEDIA
- EQ MEDIA
- périphérique MEDIA

Le switch doit être **rapide** et **sans rebuild massif** du backend.

## 4.3 EQ par canal

Même si plusieurs canaux sortent sur le **même périphérique**, chaque canal doit garder :

- son propre EQ
- son propre volume
- son propre mute

Exemple :

```text
GAME -> EQ GAME -> Headset bus
CHAT -> EQ CHAT -> Headset bus
MORE -> EQ MORE -> Headset bus
```

Tous peuvent finir sur le même casque, tout en gardant des traitements séparés avant agrégation.

## 4.4 Périphérique par canal

Exemple supporté :

- `MEDIA -> Speakers`
- `GAME -> ANPW`
- `CHAT -> ANPW`

La V2 ne doit pas exiger une seule sortie globale.  
La V2 doit permettre **un rendu final par périphérique actif**.

---

## 5. Ce qui reste hors scope immédiat

Le chantier **micro / retour micro / EasyEffects** doit être traité séparément.

Pour la première vraie phase V2, la priorité est :

- playback
- routing app
- EQ par canal
- device target par canal
- stabilité

---

## 6. Stratégie de production

## 6.1 Même repo, mais isolation complète

La V2 doit vivre dans le **même repo logique**, mais avec :

- repo/copier de travail séparée, ex. `~/k-sound-hub-v2`
- config séparée, ex. `~/.config/ksound-hub-v2`
- socket IPC séparé
- desktop entry séparé
- nom applicatif séparé : `K-Sound Hub V2`

Objectif :
- tester sans casser la version stable
- rollback immédiat
- pas de confusion

## 6.2 Branch recommandée

- branche de travail dédiée, par exemple `v2-audio-engine`
- repo GitHub inchangé
- upload plus tard seulement si la V2 est validée localement

---

## 7. Phases de migration

## Phase 0 — Fondation V2 isolée
C’est ce que contient le package joint :

- copie isolée du projet actuel
- nommage V2
- config/runtime séparés
- commande de déploiement
- arrêt des anciens process pour éviter les conflits

## Phase 1 — Instrumentation playback
Ajouter des snapshots runtime ciblés pour attraper :

- canaux actifs
- targets actifs
- état des process EQ
- état des streams déplacés

## Phase 2 — Abstraction Channel Processor
Créer une couche interne claire pour :

- channel input
- channel state
- channel EQ
- channel output selection

Sans casser l’UI.

## Phase 3 — Device Bus Layer
Introduire une couche **device bus** :

- `headset_bus`
- `spdif_bus`
- `speakers_bus`

Les channels ne sortent plus directement vers le device physique ; ils sortent vers le bus du device choisi.

## Phase 4 — Renderer final par périphérique
Créer un rendu final par device actif :

- mix final headset -> ANPW
- mix final SPDIF -> S/PDIF
- mix final speakers -> HP

## Phase 5 — Routing app / fast move
Stabiliser le move app :

- `ALL` comme entrée par défaut
- relocation rapide vers `GAME / CHAT / MEDIA / MORE`
- refresh UI léger
- pas de rebuild global à chaque action

## Phase 6 — Meters / overlay / polish
Une fois le backend playback sain :

- recalibrage meters
- overlay
- fluidité UI
- métriques runtime

## Phase 7 — Micro séparé
Chantier futur :
- EasyEffects
- double monitor si voulu
- chemins micro séparés de la V2 playback

---

## 8. Mapping concret des composants

## 8.1 Ce qui peut rester
- UI principale
- settings store
- modèles de channels
- overlay bridge
- routing app via couche Pulse/pipewire-pulse
- logique de canaux visibles

## 8.2 Ce qui devra être refait ou encapsulé
- moteur EQ playback
- topologie de sortie finale
- agrégation par device
- transitions runtime fragiles

## 8.3 Fichiers pressentis à toucher plus tard
- `src/ksound_hub/audio/pipewire.py`
- `src/ksound_hub/audio/engine.py`
- `src/ksound_hub/ui/main_window.py`
- `src/ksound_hub/ui/channel_widget.py`
- `src/ksound_hub/models.py`
- `scripts/start_ksound_hub*.sh`

---

## 9. Critères de succès

La V2 sera considérée valide si elle garde :

- même UX générale
- mêmes canaux
- même logique ALL par défaut
- EQ par canal
- device target par canal
- move d’app quasi instantané

et améliore :

- robustesse playback
- réduction des crépitements
- réduction des états intermédiaires fragiles
- isolation de la config/test/rollback

---

## 10. Décision recommandée

Lancer la V2 comme **fondation isolée** maintenant, puis migrer le backend playback par phases courtes, sans casser la base stable actuelle.
