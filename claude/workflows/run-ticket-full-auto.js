// run-ticket-full-auto — pipeline SDLC FULL AUTO pour env d'INTÉGRATION.
// Variante de run-ticket SANS gate humaine : review -> deploy branche -> recette (+fix-loop)
//   -> [si recette OK] merge MR -> deploy main. Bail-out (needs_human) uniquement sur ÉCHEC.
// ⚠️ À n'utiliser QUE sur un env d'intégration (ou une prod non ouverte utilisée comme tel).
//    Pour une vraie prod live, utiliser run-ticket (gate deploy = human-confirm).
// Lancer : Workflow({ name: 'run-ticket-full-auto',
//   args: { ticket:'SAMPLE-APPS-1', epic:'SAMPLE-APPS', branch:'feat/SAMPLE-APPS-1-applications-endrealm', mr:'76' } })
export const meta = {
  name: 'run-ticket-full-auto',
  description: "Pipeline SDLC FULL AUTO (env d'intégration) : review -> deploy branche -> recette (+fix-loop) -> merge -> deploy main",
  phases: [
    { title: 'Review' },
    { title: 'Deploy branche' },
    { title: 'Recette' },
    { title: 'Merge + Deploy main' },
  ],
}

const TICKET = (args && args.ticket) || 'SAMPLE-APPS-1'
const EPIC = (args && args.epic) || 'SAMPLE-APPS'
const REPO = (args && args.repo) || '<workspace>/app-repo'
const SDLC_ROOT = (args && args.sdlcRoot) || '<workspace>/sample-proj-sdlc-local'
const STORY = `${SDLC_ROOT}/${EPIC}/stories/${TICKET}`
const BRANCH = (args && args.branch) || `feat/${TICKET}`
const MR = (args && args.mr) || ''
const TARGET = (args && args.target) || 'main'          // branche cible du merge
const MAX_FIX = 2

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

const reviewPrompt = () => `Story SDLC **${TICKET}** (${REPO}). Review le diff de ${BRANCH} vs ${TARGET} contre les INVARIANTS de ${STORY}/spec-tech.md (+ critères ${STORY}/spec-func.md). Diff: \`git -C ${REPO} diff ${TARGET}...${BRANCH}\`. Vérifie chaque invariant (preuve), cherche bugs/régressions/fuites. Écris ${STORY}/review.md. Ne modifie PAS le code. Dernier message = JSON {conform, note, violations}.`

const deployBranchPrompt = () => `Story SDLC **${TICKET}**. Déploie la BRANCHE **${BRANCH}** de ${REPO} sur l'env d'INTÉGRATION.
Jenkins job (casse EXACTE, minuscules) : \`/job/prod/job/app-service/job/ci/\` (CI) et \`.../job/cd/\` (CD). Auth \`curl -s -n\`, jamais \`-L\`.
**AVANT de déclencher** : vérifie s'il existe déjà un build CI **en cours ou récent pour le commit de ${BRANCH}** (ex. #115) → si oui, **SUIS-LE** (ne re-déclenche PAS). Sinon → Replay CODE_BRANCH=${BRANCH} depuis un build récent.
Quand CI = SUCCESS → assure/suis le **CD**, puis vérifie la **santé** /actuator/health et récupère la version. Sur échec/ambiguïté -> {ok:false, note}. Écris ${STORY}/deploy.md. Dernier message = JSON {ok, version, note}.`

const recettePrompt = () => `Story SDLC **${TICKET}**. Recette sur l'env déployé vs les critères d'acceptation de ${STORY}/spec-func.md. Backend -> pilote l'API ; UI -> Playwright MCP. Anti-flaky: rejoue 3x. Sur KO produit un bundle repro dans ${STORY}/repro/. Écris ${STORY}/acceptance.md. Dernier message = JSON {pass, repro, flaky, failed}.`

const fixPrompt = (repro) => `Story SDLC **${TICKET}**. Recette KO. Monte l’env local du projet, rejoue le repro (${repro}), corrige sans casser les invariants (${STORY}/spec-tech.md), re-run local jusqu'au vert, commit + push sur ${BRANCH}. Dernier message = JSON {fixed, root_cause, commit}.`

const mergePrompt = () => `Story SDLC **${TICKET}**. Recette verte -> merge la MR **!${MR}** (${BRANCH} -> ${TARGET}) via \`env -u GITLAB_TOKEN glab mr merge ${MR}\` dans ${REPO}. Vérifie que le merge est effectif. Sur échec/conflit -> {merged:false, note}. Dernier message = JSON {merged, note}.`

const deployMainPrompt = () => `Story SDLC **${TICKET}**. Déploie **${TARGET}** (mergé) sur l'env d'intégration via le pipeline prod normal (build depuis ${TARGET}). Vérifie /actuator/health. Sur erreur -> {ok:false, note}. Append ${STORY}/deploy.md. Dernier message = JSON {ok, version, note}.`

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

log(`✅ ${TICKET} : mergé + déployé (${depMain.version})`)
return { stopped_at: 'done', reason: 'accepted', version: depMain.version, review: rev }
