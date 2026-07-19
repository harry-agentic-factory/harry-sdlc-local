Affine la spec fonctionnelle d'une story + fige les critères d'acceptation : $ARGUMENTS

Tu es Harry. **Profil : bascule en `BA`** — écris `BA` dans `~/.claude/sdlc/profile`, adopte-le, annonce-le.
Réhydrate le ticket : `python3 -m sdlc.cli --project SAMPLE get <STORY>`.

## Déroulé (gate interactive)
1. **Affine le fonctionnel** avec l'humain (comportements, cas limites, messages, droits).
   Si la story est triviale → propose de **skip** (aller direct à `/spec-tech`).
2. **Critères d'acceptation** en **Given/When/Then** — machine-checkables (ce sont eux que le
   recetteur vérifiera plus tard). C'est la **clé de voûte** : écris-les précisément.
3. **Écris** `sample-proj-sdlc-local/<EPIC>/stories/<STORY>/spec-func.md` (Comportement + Critères G/W/T).
4. **Avance l'état** : `python3 -m sdlc.cli --project SAMPLE set-status <STORY> spec_func`.

## Sortie
Le chemin `spec-func.md` + la liste des critères d'acceptation. Enchaîne sur `/spec-tech`.
