# Scheduled jobs — pattern de job planifié maîtrisé

> Pattern généralisé (d'un lot « job planifié » réel) pour tout **traitement récurrent** multi-réplicas,
> observable et rejouable. Léger et project-agnostic. Direction cible pour les cas lourds : **Spring Batch**.
> Réf depuis `docs/loop-engineering.md` et l'agent `deployer` quand une story ajoute un job planifié.

## Les briques (chacune répond à un mode de panne connu)

1. **Fenêtre déterministe** — le job traite une **fenêtre de temps calculée**, pas « depuis la dernière
   fois » : ex. **n‑1** (période précédente), en **UTC**, bornes **closed-open** `[start, end)` (pas de
   chevauchement ni de trou entre deux runs). La fenêtre est **fonction pure** de l'instant de déclenchement
   → un run est **rejouable** à l'identique.

2. **ShedLock** — garantit **une seule exécution entre réplicas** (le `@Scheduled` fire sur chaque pod). Lock
   **auto-expirant** (`lockAtMostFor` > durée max plausible du job) pour ne pas rester bloqué si un pod meurt
   en tenant le lock.

3. **Run-history persistée** — **une row par run** dans une table dédiée :
   - `status` ∈ `RUNNING | SUCCESS | TIMEOUT | FAILED` (+ `PARTIAL`, cf. isolation par-tenant) ;
   - `expires_at` **calculé au start** (start + timeout budget) → sert au reclaim ;
   - `report` (résumé : compteurs, fenêtre traitée, erreurs) ;
   - `runId`, `started_at`, `finished_at`, fenêtre `[start,end)`.
   Rend le job **auditables** (qu'a-t-il fait, quand, avec quel résultat) et **idempotent-friendly**.

4. **Reclaim des runs expirés → TIMEOUT** — au démarrage d'un run (ou via un balai), tout run **`RUNNING`
   dont `expires_at` est dépassé** est repassé en **`TIMEOUT`** : **anti-blocage** si un run est mort sans
   écrire son statut final (pod tué, OOM). Sans ça, un `RUNNING` fantôme bloque les runs suivants.

5. **Déclencheur on-demand async** — un endpoint (admin) permet de **lancer le job à la demande**, en
   **async**, en **partageant le MÊME launcher** que le `@Scheduled` (**DRY** : une seule logique de run,
   deux déclencheurs). Le on-demand accepte typiquement une fenêtre explicite (rejeu ciblé).

6. **Logs traçables (`runId`)** — chaque ligne de log porte le **`runId`** → on suit un run de bout en bout
   dans des logs entrelacés (multi-tenant, multi-pod).

7. **Isolation par-tenant** — boucle **try/catch par tenant** : l'échec d'un tenant **n'arrête pas** les
   autres ; le run finit en **`PARTIAL`** (statut dédié) avec le détail des tenants OK/KO dans le `report`.

## Squelette (indicatif)
```
@Scheduled(cron = "...", zone = "UTC")   ─┐
                                          ├─▶  runLauncher.run(window)   // launcher UNIQUE (DRY)
POST /admin/jobs/<job>/run  (async)      ─┘         │
                                                     ├─ reclaim: RUNNING & expires_at<now → TIMEOUT
                                                     ├─ @SchedulerLock (ShedLock, lockAtMostFor)
                                                     ├─ history.start(runId, window, expires_at) → RUNNING
                                                     ├─ for tenant: try{ process } catch{ mark tenant KO }
                                                     └─ history.finish(runId, SUCCESS|PARTIAL|FAILED, report)
```

## Quand passer à Spring Batch
Dès que le job devient **lourd** (gros volumes, étapes multiples, chunk/restart, reprise sur incident,
parallélisme partitionné) : Spring Batch apporte `JobRepository` (équivalent durci de la run-history),
chunk-oriented processing, restartabilité et métriques. Le pattern ci-dessus reste la **version légère** ;
Spring Batch en est la **montée en charge** naturelle.

## Validation (iso-prod — cf. `docs/prod-faithful-validation.md`)
- La **run-history** et le lock ShedLock écrivent en base → valider sur le **vrai moteur** (Postgres), pas H2
  (types de colonnes date/`jsonb` du `report`, contraintes).
- Le `@Scheduled` / le wiring du launcher = **échec au boot** possible → couvrir par un **smoke
  context-load** (`@SpringBootTest`).
- Fenêtre déterministe + reclaim = logique **pure/déterministe** → **IT au build** (seed-direct, bords :
  run expiré, tenant KO → PARTIAL, closed-open sans trou/chevauchement).

## Références croisées
- `docs/loop-engineering.md` / skill `loop-engineering` — répartition IT-au-build vs live.
- `docs/prod-faithful-validation.md` — must-run gates (IT Postgres + smoke context-load).
