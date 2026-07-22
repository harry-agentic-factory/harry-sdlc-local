// run-ticket-full-auto — pipeline SDLC FULL AUTO pour env d'INTÉGRATION.
// Variante de run-ticket SANS gate humaine : review -> deploy branche -> recette (+fix-loop)
//   -> [si recette OK] merge MR -> deploy main. Bail-out (needs_human) uniquement sur ÉCHEC.
// ⚠️ À n'utiliser QUE sur un env d'intégration (ou une prod non ouverte utilisée comme tel).
//    Pour une vraie prod live, utiliser run-ticket (gate deploy = human-confirm).
// Lancer : Workflow({ name: 'run-ticket-full-auto', args: 'SAMPLE-GATES-1' })   // ID seul (epic/repo/branch/mr auto-résolus)
//     ou : Workflow({ name: 'run-ticket-full-auto', args: { ticket, epic, branch, mr, target } })
export const meta = {
  name: 'run-ticket-full-auto',
  description: "Pipeline SDLC FULL AUTO (env d'intégration) : review -> deploy branche -> recette (+fix-loop) -> merge -> deploy main",
  phases: [
    { title: 'Prepare' },
    { title: 'Review' },
    { title: 'Deploy branche' },
    { title: 'Recette' },
    { title: 'Merge + Deploy main' },
    { title: 'Cleanup' },
  ],
}

// ── paramètres (args tolérant : objet | string "ID de ticket" | JSON-string) ──
let A = args
if (typeof A === 'string') {
  const s = A.trim()
  A = s.startsWith('{') ? (() => { try { return JSON.parse(s) } catch { return { ticket: s } } })()
                        : { ticket: s }
}
A = A || {}
const TICKET = A.ticket || 'SAMPLE-APPS-1'
const PREFIX = A.prefix || (TICKET.includes('-') ? TICKET.split('-')[0] : 'SAMPLE')
const TARGET = A.target || 'main'          // branche cible du merge
// valeurs faibles — écrasées par la résolution de la phase Prepare (via `sdlc config`/`get`)
let EPIC = A.epic
let REPO_NAME = A.repoName
let REPO = A.repo
let SDLC_ROOT = A.sdlcRoot
let BRANCH = A.branch || `feat/${TICKET}`
let MR = A.mr || ''
let STORY = ''            // calculé après résolution Prepare
const MAX_FIX = 2
let WORKREPO = REPO   // remplacé par le worktree isolé du ticket après la phase Prepare

const REVIEW = { type: 'object', required: ['conform'], properties: {
  conform: { type: 'boolean' }, note: { type: 'string' }, violations: { type: 'array', items: { type: 'string' } } } }
const DEPLOY = { type: 'object', required: ['ok'], properties: {
  ok: { type: 'boolean' }, version: { type: 'string' }, note: { type: 'string' } } }
const RECETTE = { type: 'object', required: ['pass'], properties: {
  pass: { type: 'boolean' }, repro: { type: 'string' }, flaky: { type: 'boolean' }, failed: { type: 'array', items: { type: 'string' } } } }
const FIX = { type: 'object', required: ['fixed'], properties: {
  fixed: { type: 'boolean' }, root_cause: { type: 'string' }, commit: { type: 'string' } } }
const MERGE = { type: 'object', required: ['merged'], properties: {
  merged: { type: 'boolean' }, note: { type: 'string' } } }
const WS = { type: 'object', required: ['resolved'], properties: {
  resolved: { type: 'boolean' }, worktree: { type: 'string' },
  epic: { type: 'string' }, repoName: { type: 'string' }, repo: { type: 'string' },
  sdlcRoot: { type: 'string' }, branch: { type: 'string' }, mr: { type: 'string' },
  additionalDirectories: { type: 'array', items: { type: 'string' } },
  projectSkills: { type: 'array', items: { type: 'string' } }, note: { type: 'string' } } }
const CLEAN = { type: 'object', properties: { cleaned: { type: 'boolean' }, note: { type: 'string' } } }

const prepPrompt = () => `Prépare la **bulle scopée** du ticket **${TICKET}** (préfixe projet **${PREFIX}**).
1. **Résous la config** en Bash :
   - \`sdlc --project ${PREFIX} get ${TICKET}\` → si le ticket est introuvable (erreur/"introuvable"), renvoie \`{"resolved":false,"note":"ticket ${TICKET} introuvable"}\` et NE crée RIEN. Sinon récupère \`epic\`, la 1re entrée de \`repos[]\` (= repoName), \`branch\` (sinon \`feat/${TICKET}\`) et \`mr\` (si présent).
   - \`sdlc --project ${PREFIX} config\` → \`workspace\` (= sdlcRoot), le chemin du repo via \`repos[repoName]\` (= repo).
2. **Crée la bulle** : \`sdlc --project ${PREFIX} workspace ${TICKET} --branch <branch résolue>\` → worktree isolé + \`.claude/settings.json\` (additionalDirectories) + symlink des skills projet.
Renvoie STRICTEMENT le JSON : \`{resolved:true, worktree (= .worktrees[repoName]), epic, repoName, repo, sdlcRoot, branch, mr, additionalDirectories, projectSkills}\`. Ne fais RIEN d'autre.`

const reviewPrompt = () => `Story SDLC **${TICKET}** (${WORKREPO}). Review le diff de ${BRANCH} vs ${TARGET} contre les INVARIANTS de ${STORY}/spec-tech.md (+ critères ${STORY}/spec-func.md). Diff: \`git -C ${WORKREPO} diff ${TARGET}...${BRANCH}\`. Vérifie chaque invariant (preuve), cherche bugs/régressions/fuites. Écris ${STORY}/review.md. Ne modifie PAS le code. **Transition dictée par l'orchestration — si conforme** : \`sdlc --project ${PREFIX} set-status ${TICKET} reviewed\`. Dernier message = JSON {conform, note, violations}.`

const deployBranchPrompt = () => `Story SDLC **${TICKET}**. Déploie la BRANCHE **${BRANCH}** de ${WORKREPO} sur l'env d'INTÉGRATION.
Jenkins job (casse EXACTE, minuscules) : \`/job/prod/job/app-service/job/ci/\` (CI) et \`.../job/cd/\` (CD). Auth \`curl -s -n\`, jamais \`-L\`.
**AVANT de déclencher** : vérifie s'il existe déjà un build CI **en cours ou récent pour le commit de ${BRANCH}** (ex. #115) → si oui, **SUIS-LE** (ne re-déclenche PAS). Sinon → Replay CODE_BRANCH=${BRANCH} depuis un build récent.
Quand CI = SUCCESS → assure/suis le **CD**, puis vérifie la **santé** /actuator/health et récupère la version. Sur échec/ambiguïté -> {ok:false, note}. Écris ${STORY}/deploy.md. **Transition dictée par l'orchestration — si succès** : \`sdlc --project ${PREFIX} set-status ${TICKET} deployed\`. Dernier message = JSON {ok, version, note}.`

const recettePrompt = () => `Story SDLC **${TICKET}**. Recette sur l'env déployé vs les critères d'acceptation de ${STORY}/spec-func.md. Backend -> pilote l'API ; UI -> Playwright MCP. Anti-flaky: rejoue 3x. Sur KO produit un bundle repro dans ${STORY}/repro/. Écris ${STORY}/acceptance.md. **Transition dictée par l'orchestration — si tous les critères passent** : \`sdlc --project ${PREFIX} set-status ${TICKET} recette_ok\`. Dernier message = JSON {pass, repro, flaky, failed}.`

const fixPrompt = (repro) => `Story SDLC **${TICKET}**. Recette KO. **Transitions dictées par l'orchestration** : au démarrage \`sdlc --project ${PREFIX} set-status ${TICKET} implemented\` ; après le commit \`sdlc --project ${PREFIX} set-status ${TICKET} reviewed\`. Monte l’env local du projet, rejoue le repro (${repro}), corrige sans casser les invariants (${STORY}/spec-tech.md), re-run local jusqu'au vert, commit + push sur ${BRANCH} (depuis le worktree isolé ${WORKREPO}). Dernier message = JSON {fixed, root_cause, commit}.`

const mergePrompt = () => `Story SDLC **${TICKET}**. Recette verte -> merge la MR **!${MR}** (${BRANCH} -> ${TARGET}) via \`env -u GITLAB_TOKEN glab mr merge ${MR}\` dans ${WORKREPO}. Vérifie que le merge est effectif. Sur échec/conflit -> {merged:false, note}. Dernier message = JSON {merged, note}.`

const cleanPrompt = () => `Story **${TICKET}** mergée sur ${TARGET}. (1) Exécute en Bash \`sdlc --project ${PREFIX} worktree-clean ${TICKET} --ref origin/${TARGET}\` : retire le worktree + la branche **seulement si mergée**, et supprime la bulle régénérable. (2) **Transitions finales dictées par l'orchestration** (full-auto = auto-accept) : \`sdlc --project ${PREFIX} set-status ${TICKET} accepted\` puis \`sdlc --project ${PREFIX} set-status ${TICKET} done\`. Renvoie {cleaned, note}.`

const deployMainPrompt = () => `Story SDLC **${TICKET}**. Déploie **${TARGET}** (mergé) sur l'env d'intégration via le pipeline prod normal (build depuis ${TARGET}). Vérifie /actuator/health. Sur erreur -> {ok:false, note}. Append ${STORY}/deploy.md. Dernier message = JSON {ok, version, note}.`

// ── Prepare : résout la config projet (sdlc config/get) + matérialise la bulle scopée ──
phase('Prepare')
const prep = await agent(prepPrompt(), { agentType: 'general-purpose', schema: WS, label: `prepare:${TICKET}`, phase: 'Prepare' })
if (!prep || prep.resolved === false) {
  log(`Prepare : ticket ${TICKET} non résolu -> STOP (humain). ${prep ? (prep.note || '') : 'agent KO'}`)
  return { stopped_at: 'prepare', reason: 'needs_human', detail: `ticket ${TICKET} non résolu`, prepare: prep }
}
// applique la config résolue (args explicites prioritaires, sinon résolution Prepare)
EPIC = EPIC || prep.epic
REPO_NAME = REPO_NAME || prep.repoName
REPO = REPO || prep.repo
SDLC_ROOT = SDLC_ROOT || prep.sdlcRoot
BRANCH = A.branch || prep.branch || BRANCH
MR = MR || prep.mr || ''
WORKREPO = prep.worktree || REPO
STORY = `${SDLC_ROOT}/${EPIC}/stories/${TICKET}`
// garde-fou anti-placeholder : ne jamais avancer sur des valeurs fictives
if (!EPIC || !SDLC_ROOT || !REPO || `${EPIC}${SDLC_ROOT}${REPO}`.includes('<workspace>')) {
  log('Prepare : config non résolue (placeholders restants) -> STOP (humain)')
  return { stopped_at: 'prepare', reason: 'needs_human', detail: 'config non résolue (placeholders)', prepare: prep }
}
log(`Bulle prête — ${EPIC}/${TICKET} @ ${WORKREPO}`)

// ── Review ──
phase('Review')
const rev = await agent(reviewPrompt(), { agentType: 'reviewer', schema: REVIEW, label: `review:${TICKET}`, phase: 'Review' })
if (!rev || !rev.conform) return { stopped_at: 'review', reason: 'needs_human', review: rev }
log('Review conforme ✅')

// ── Deploy branche ──
phase('Deploy branche')
let dep = await agent(deployBranchPrompt(), { agentType: 'deployer', schema: DEPLOY, label: `deploy:${TICKET}`, phase: 'Deploy branche' })
if (!dep || !dep.ok) return { stopped_at: 'deploy', reason: 'needs_human', deploy: dep }

// ── Recette (+ fix-loop) ──
phase('Recette')
let tries = 0
while (true) {
  const rec = await agent(recettePrompt(), { agentType: 'recetteur', schema: RECETTE, label: `recette:${TICKET}`, phase: 'Recette' })
  if (rec && rec.pass) { log('Recette verte ✅'); break }
  if (!rec || rec.flaky || tries >= MAX_FIX) return { stopped_at: 'recette', reason: 'needs_human', recette: rec }
  tries++
  log(`Recette KO -> fix-loop ${tries}/${MAX_FIX}`)
  await agent(fixPrompt(rec.repro), { agentType: 'fixer', schema: FIX, label: `fix:${TICKET}`, phase: 'Recette' })
  await agent(deployBranchPrompt(), { agentType: 'deployer', schema: DEPLOY, label: `redeploy:${TICKET}`, phase: 'Recette' })
}

// ── Merge + Deploy main (FULL AUTO : pas de gate humaine) ──
phase('Merge + Deploy main')
const merged = await agent(mergePrompt(), { schema: MERGE, label: `merge:${TICKET}`, phase: 'Merge + Deploy main' })
if (!merged || !merged.merged) return { stopped_at: 'merge', reason: 'needs_human', merge: merged }
const depMain = await agent(deployMainPrompt(), { agentType: 'deployer', schema: DEPLOY, label: `deploy-main:${TICKET}`, phase: 'Merge + Deploy main' })
if (!depMain || !depMain.ok) return { stopped_at: 'deploy-main', reason: 'needs_human', deploy: depMain }

// ── Cleanup : retire le worktree du ticket (mergé) + la bulle régénérable ──
phase('Cleanup')
const cln = await agent(cleanPrompt(), { agentType: 'general-purpose', schema: CLEAN, label: `cleanup:${TICKET}`, phase: 'Cleanup' })
log(cln && cln.cleaned ? '🧹 worktree + bulle nettoyés' : `Cleanup: ${cln ? (cln.note || 'rien à nettoyer') : 'non exécuté'}`)

log(`✅ ${TICKET} : mergé + déployé (${depMain.version})`)
return { stopped_at: 'done', reason: 'accepted', version: depMain.version, review: rev }
