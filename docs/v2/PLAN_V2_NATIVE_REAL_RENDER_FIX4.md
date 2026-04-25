# K-Sound Hub V2 – Native Real Render Fix 4

Objectif:
- réduire les crépitements lors du démarrage/fermeture d'apps
- adoucir les transitions d'arrivée/disparition de flux
- préserver l'état interne des biquads lors des reloads d'état identiques

Changements:
- préservation de l'état des filtres EQ si la forme des filtres n'a pas changé
- gate/ramp courte par canal dans le moteur natif
- petit hold avant coupure complète d'un canal silencieux
- gap-fill très court sur underflow de capture pour éviter les coupures nettes

Pas de changement:
- architecture native réelle inchangée
- helpers `parec`/`pacat` inchangés vs fix3
- UI inchangée
