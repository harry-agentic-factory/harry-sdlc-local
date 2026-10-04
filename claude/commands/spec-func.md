Affine la spec fonctionnelle d'une story + fige les critères d'acceptation : $ARGUMENTS

Tu es Harry. **Profil : bascule en `BA`** — adopte ce profil pour la suite de la session (in-session, pas de fichier), sans l'annoncer (« Écrire pour un humain »).
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
   - **Section « Tests obligatoires au build »** (les *must-run*) : liste les tests unit/IT/e2e/non-reg à jouer
     (+ assertions sur le diff : grep, invariants) — ce sont des *gates*, pas des optionnels.
   - But : rendre la recette **explicite et reproductible** (finies les assertions vagues « ça s'affiche »).
3. **Écris** `sample-proj-sdlc-local/<EPIC>/stories/<STORY>/spec-func.md` au **format FIXE** ci-dessous.
4. **Avance l'état** : `python3 -m sdlc.cli --project SAMPLE set-status <STORY> spec_func`.

## Format FIXE de `spec-func.md`
Règle « Format des livrables » de la persona : un seul titre `#`, puis exactement ces sections `##`, dans cet ordre,
sans suffixe (pas de « (Given/When/Then) » ni de « (must-run) » dans les titres) :

```markdown
# <STORY> — <titre>

## Comportement
<comportements, cas limites, messages, droits>

## Critères d'acceptation
- **AC1** — Given <contexte>, When <action>, Then <résultat attendu>.
  - 🔬 Must-validate : <appel exact ou étape UI>, identité <compte de recette>, assertion <valeur chiffrée>.
- **AC2** — Given …, When …, Then ….
  - 🔬 Must-validate : ….

## Tests obligatoires au build
<tests unit/IT/e2e/non-reg à jouer + assertions sur le diff>

## Sources
<PRD, refine, Brain, code>
```

Exactement **un** « 🔬 Must-validate » sous **chaque** critère. N'écris pas « Comportement attendu » ni
« Comportement (cible) » : écris `## Comportement`. N'écris pas « Critères d'acceptation (Given/When/Then) », « (G/W/T) »
ni « Acceptance » : écris `## Critères d'acceptation`. N'écris pas « Tests obligatoires au build (must-run) » ni
« Tests » : écris `## Tests obligatoires au build`. Rien d'autre au niveau `##` : « Contexte », « Objectif », « User
stories », « Droits », « Cas limites », « Hors périmètre », « Décisions prises en l'absence du PO », « Points pour la
spec technique » sont des `###` sous Comportement. Une spec existante écrite autrement : à sa réécriture, ses
sections sont renommées vers ces noms et leur contenu y est rangé, sans rien perdre.

> **Avant d'écrire un document vivant** du dépôt data : règle « Écrire un document vivant » de la persona (`~/.claude/sdlc/harry.md`).

## Sortie
Dis à l'humain (règle « Écrire pour un humain » de la persona) : la spec fonctionnelle est écrite, et ses critères d'acceptation en une ligne chacun.

**Ensuite — la gate FONCTIONNELLE, de préférence au niveau ÉPIC** : `/validate-spec-func <EPIC>` (ou `<STORY>`),
quand tous les `spec-func` de l'épic sont écrits. L'agent recommande, l'humain décide :

```bash
# 1. harry-archi (mode document de revue) relit PRD + refine + TOUS les spec-func → <EPIC>/review-spec-func.md
# 2. /process-review <EPIC>/review-spec-func.md → <EPIC>/review-spec-func-verdict.md, signé par l'HUMAIN
# 3. consignation (refusée sans verdict signé) :
sdlc --project <PREFIX> validate-spec-func <EPIC> --verdict <EPIC>/review-spec-func-verdict.md
```

Pourquoi à l'épic plutôt que par story : une erreur fonctionnelle coûte d'autant plus cher qu'on a déjà
bâti le technique par-dessus. La valider **avant** `/spec-tech`, sur tout le lot, attrape les
incohérences **entre** stories — celles qu'une relecture story par story ne voit jamais.

Sur une story isolée et triviale, la gate est sautable (`spec_func → spec_tech` reste permis) : note-le.
Ancien nom de la sous-commande : `validate-func` (alias).

**Puis** `/spec-tech`.
