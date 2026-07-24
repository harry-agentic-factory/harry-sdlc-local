// run-ticket — pipeline autonome d'un ticket SDLC (Harry).
// Calque sample-proj-sdlc-local/tooling/sdlc/orchestrator.py (logique de référence testée en stub).
// Lancer : Workflow({ name: 'run-ticket', args: { ticket: 'SAMPLE-APPS-1', epic: 'SAMPLE-APPS' } })
export const meta = {
  name: 'run-ticket',
  description: "Pipeline autonome d'un ticket SDLC : reviewer -> deployer -> recette (+ fix-loop), gates + escalation",
  phases: [
    { title: 'Prepare' },
    { title: 'Review' },
    { title: 'Deploy' },
    { title: 'Recette' },
    { title: 'Promote' },
  ],
}

// ── paramètres ──
const TICKET = (args && args.ticket) || 'SAMPLE-APPS-1'
const EPIC = (args && args.epic) || 'SAMPLE-APPS'
const PREFIX = (args && args.prefix) || 'SAMPLE'
const REPO_NAME = (args && args.repoName) || 'app-repo'
const REPO = (args && args.repo) || '<workspace>/app-repo'
const BRANCH = (args && args.branch) || `feat/${TICKET}`
const SDLC_ROOT = (args && args.sdlcRoot) || '<workspace>/sample-proj-sdlc-local'
const STORY = `${SDLC_ROOT}/${EPIC}/stories/${TICKET}`
const ESC = (args && args.escalation) || { review: 'auto', deploy: 'auto', recette: 'auto', promote: 'human' }
const PROMOTE = !!(args && args.promote)   // true = phase C (après validation humaine de la recette) : merge main + deploy prod
const REVIEW_HUMAN = ((((args && args.review) || ESC.review) || 'human') === 'human')  // option : gate review humaine (défaut) vs review auto
const REVIEW_OK = !!(args && args.reviewOk) // review humaine déjà approuvée -> on reprend directement au deploy branche
const MAX_FIX = 2
let WORKREPO = REPO   // remplacé par le worktree isolé du ticket après la phase Prepare

const REVIEW = { type: 'object', required: ['conform'], properties: {
  conform: { type: 'boolean' }, note: { type: 'string' },
  violations: { type: 'array', items: { type: 'string' } } } }
const DEPLOY = { type: 'object', required: ['ok'], properties: {
  ok: { type: 'boolean' }, version: { type: 'string' }, note: { type: 'string' } } }
const RECETTE = { type: 'object', required: ['pass'], properties: {
  pass: { type: 'boolean' }, repro: { type: 'string' }, flaky: { type: 'boolean' },
  failed: { type: 'array', items: { type: 'string' } } } }
const FIX = { type: 'object', required: ['fixed'], properties: {
  fixed: { type: 'boolean' }, root_cause: { type: 'string' }, commit: { type: 'string' } } }

const WS = { type: 'object', required: ['worktree'], properties: {
  worktree: { type: 'string' }, additionalDirectories: { type: 'array', items: { type: 'string' } },
  projectSkills: { type: 'array', items: { type: 'string' } } } }

const prepPrompt = () => `Prépare la **bulle scopée** du ticket **${TICKET}**. Exécute en Bash :
\`sdlc --project ${PREFIX} workspace ${TICKET} --branch ${BRANCH}\`
→ crée le worktree isolé + \`.claude/settings.json\` (additionalDirectories = worktrees+brain+data) + symlink des skills projet. Renvoie STRICTEMENT le JSON : worktree = \`.worktrees["${REPO_NAME}"]\`, additionalDirectories, projectSkills. Ne fais RIEN d'autre.`

const reviewPrompt = () => `Story SDLC **${TICKET}** (${WORKREPO}). Review le diff de la branche vs main contre les INVARIANTS du spec-tech.
Lis: ${STORY}/spec-tech.md (invariants = ta checklist) + ${STORY}/spec-func.md (critères).
Diff: \`git -C ${WORKREPO} diff main...HEAD\`. Vérifie CHAQUE invariant (preuve dans le diff), cherche bugs/régressions/fuites. Écris ${STORY}/review.md. Ne modifie PAS le code.
**Transition dictée par l'orchestration — si (et seulement si) conforme** : \`sdlc --project ${PREFIX} set-status ${TICKET} reviewed\`. Ne décide d'aucune autre transition.
Dernier message = JSON {conform, note, violations}.`

const deployPrompt = () => `Story SDLC **${TICKET}**. **Étape 1/2 — DÉPLOIE LA BRANCHE \`${BRANCH}\` EN INTÉGRATION** (skill deploy-jenkins : Replay \`CODE_BRANCH=${BRANCH}\` sur le job CI du repo → suivre → CD → santé/version). **NE touche PAS à main, NE merge PAS** — on déploie la branche pour la recetter. Vérifie la santé (/actuator/health) + l'image déployée = bien celle de la branche. **Sécurité : si l'env n'est pas prêt, ou si une action est ambiguë/risquée/irréversible, NE déploie PAS → {ok:false, note:"raison"}.** Écris ${STORY}/deploy.md. **Transition dictée par l'orchestration — si le déploiement branche réussit** : \`sdlc --project ${PREFIX} set-status ${TICKET} deployed\`. Dernier message = JSON {ok, version, note}.`

const promotePrompt = () => `Story SDLC **${TICKET}** VALIDÉE par l'humain — **Étape 2/2 — PROMOTE (merge + PROD)**.
1) **Merge** la MR de la branche \`${BRANCH}\` → main (glab, **TA propre MR** ; **jamais** de push direct sur main).
2) **Déploie main EN PROD** (skill deploy-jenkins : CI sur \`main\` → CD, ou Replay \`CODE_BRANCH=main\`), suis jusqu'au bout, **vérifie l'image prod déployée + santé** (la prod doit refléter le merge).
Écris ${STORY}/deploy.md (section « promote/prod »). **Transitions dictées par l'orchestration si ok** : \`sdlc --project ${PREFIX} set-status ${TICKET} accepted\` puis, prod vérifiée, \`sdlc --project ${PREFIX} set-status ${TICKET} done\`. Dernier message = JSON {ok, version, note}.`

const recettePrompt = () => `Story SDLC **${TICKET}**. Recette sur l'env déployé vs les critères d'acceptation de ${STORY}/spec-func.md. Feature backend -> pilote l'API ; UI -> Playwright MCP. Anti-flaky: rejoue 3x. Sur KO produit un bundle repro dans ${STORY}/repro/. Écris ${STORY}/acceptance.md. **Transition dictée par l'orchestration — si tous les critères passent** : \`sdlc --project ${PREFIX} set-status ${TICKET} recette_ok\`. Dernier message = JSON {pass, repro, flaky, failed}.`

const fixPrompt = (repro) => `Story SDLC **${TICKET}**. Recette KO. **Transitions dictées par l'orchestration** : au démarrage \`sdlc --project ${PREFIX} set-status ${TICKET} implemented\` (retour dev) ; après le commit \`sdlc --project ${PREFIX} set-status ${TICKET} reviewed\`. Monte l’env local du projet, rejoue le bundle repro (${repro}), corrige le code sans casser les invariants (${STORY}/spec-tech.md), re-run en local jusqu'au vert, commit sur la branche. Dernier message = JSON {fixed, root_cause, commit}.`

// ── PHASE B — PROMOTE : déclenchée APRÈS validation humaine (args.promote=true). Merge main + deploy PROD ──
// (pas besoin de worktree : le deployer merge la MR puis déploie main via Jenkins)
if (PROMOTE) {
  phase('Promote')
  log(`Validation humaine reçue -> PROMOTE ${TICKET} : merge ${BRANCH} -> main + deploy PROD`)
  const prom = await agent(promotePrompt(), { agentType: 'deployer', schema: DEPLOY, label: `promote:${TICKET}`, phase: 'Promote' })
  if (!prom || !prom.ok) return { stopped_at: 'promote', reason: 'needs_human', promote: prom }
  log(`Promote OK ✅ — main déployé en prod: ${prom.version}`)
  return { stopped_at: 'promote', reason: 'done', promote: prom }
}

// ── PHASE A — PREPARE : matérialise la bulle scopée (worktree isolé + settings + skills projet) ──
phase('Prepare')
const prep = await agent(prepPrompt(), { agentType: 'general-purpose', schema: WS, label: `prepare:${TICKET}`, phase: 'Prepare' })
if (prep && prep.worktree) { WORKREPO = prep.worktree; log(`Bulle prête — worktree isolé: ${WORKREPO}${(prep.projectSkills||[]).length ? ' | skills projet: '+prep.projectSkills.join(',') : ''}`) }
else log(`Prepare KO -> repli sur ${WORKREPO} (working tree partagé)`)

// ── PHASE A — REVIEW : option `review` = 'human' (gate, défaut) | 'auto'. Sautée si reprise après approbation ──
let rev = null
if (!REVIEW_OK) {
  phase('Review')
  rev = await agent(reviewPrompt(), { agentType: 'reviewer', schema: REVIEW, label: `review:${TICKET}`, phase: 'Review' })
  if (!rev || !rev.conform) {
    log(`Review NON conforme -> STOP (humain). Violations: ${rev ? (rev.violations || []).join(' | ') : 'agent KO'}`)
    return { stopped_at: 'review', reason: 'needs_human', review: rev }
  }
  log('Review conforme ✅')
  if (REVIEW_HUMAN) {
    log('Gate review = HUMAINE -> STOP, en attente de ton approbation. Relance avec {reviewOk:true} pour continuer (deploy branche + recette).')
    return { stopped_at: 'review', reason: 'await_review', review: rev }
  }
} else {
  log('Review humaine déjà approuvée (reviewOk) -> reprise directe au deploy branche.')
}

// ── DEPLOY BRANCHE (direct, intégration — jamais main) ──
phase('Deploy')
const dep = await agent(deployPrompt(), { agentType: 'deployer', schema: DEPLOY, label: `deploy:${TICKET}`, phase: 'Deploy' })
if (!dep || !dep.ok) return { stopped_at: 'deploy', reason: 'needs_human', deploy: dep, review: rev }

phase('Recette')
let tries = 0
while (true) {
  const rec = await agent(recettePrompt(), { agentType: 'recetteur', schema: RECETTE, label: `recette:${TICKET}`, phase: 'Recette' })
  if (rec && rec.pass) { log(`Recette OK ✅ sur la BRANCHE déployée -> EN ATTENTE DE TA VALIDATION. Pour promouvoir (merge main + deploy PROD) : relance run-ticket avec {promote:true}.`); return { stopped_at: 'recette', reason: 'await_validation', recette: rec } }
  if (!rec || rec.flaky || tries >= MAX_FIX) return { stopped_at: 'recette', reason: 'needs_human', recette: rec }
  tries++
  log(`Recette KO -> fix-loop ${tries}/${MAX_FIX}`)
  await agent(fixPrompt(rec.repro), { agentType: 'fixer', schema: FIX, label: `fix:${TICKET}`, phase: 'Recette' })
  await agent(deployPrompt(), { agentType: 'deployer', schema: DEPLOY, label: `redeploy:${TICKET}`, phase: 'Recette' })
}
