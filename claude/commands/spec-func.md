Affine la spec fonctionnelle d'une story + fige les critères d'acceptation : $ARGUMENTS

Tu es Harry. **Profil : bascule en `BA`** — adopte ce profil pour la suite de la session (in-session, pas de fichier), annonce-le.
Réhydrate le ticket : `python3 -m sdlc.cli --project SAMPLE get <STORY>`.

## Déroulé (gate interactive)
1. **Affine le fonctionnel** avec l'humain (comportements, cas limites, messages, droits).
   Si la story est triviale → propose de **skip** (aller direct à `/spec-tech`).
2. **Critères d'acceptation** en **Given/When/Then** — machine-checkables (ce sont eux que le
   recetteur vérifiera plus tard). C'est la **clé de voûte** : écris-les précisément.
   - **OBLIGATOIRE — « 🔬 Must-validate » par AC** : sous CHAQUE critère, cartographie le **test EXACT** à
     rejouer en recette (le *comment* concret, pas juste le *quoi*) : l'appel précis (endpoint + verbe + params,
     ou étape UI Playwright), l'**identité** de recette à utiliser, et l'**assertion CHIFFRÉE** attendue (code
     HTTP, valeur de champ, compte). Un AC sans Must-validate exécutable est incomplet.
   - **Quand un AC rejoue un bug signalé**, marque-le « reproduction obligatoire du bug » : ce test DOIT passer
     au vert avant clôture.
   - **Section « Tests obligatoires au build (must-run) »** : liste les tests unit/IT/e2e/non-reg à jouer
     (+ assertions sur le diff : grep, invariants) — ce sont des *gates*, pas des optionnels.
   - But : rendre la recette **explicite et reproductible** (finies les assertions vagues « ça s'affiche »).
3. **Écris** `sample-proj-sdlc-local/<EPIC>/stories/<STORY>/spec-func.md` (Comportement + Critères G/W/T
   **avec un 🔬 Must-validate par AC** + section « Tests obligatoires au build »).
4. **Avance l'état** : `python3 -m sdlc.cli --project SAMPLE set-status <STORY> spec_func`.

## Sortie
Le chemin `spec-func.md` + la liste des critères d'acceptation. Enchaîne sur `/spec-tech`.
