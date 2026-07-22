// run-ticket-full-auto — pipeline SDLC AUTO sur la BRANCHE du ticket (env d'INTÉGRATION).
// Modèle : TOUT se fait sur la branche du ticket (jamais main) — review -> deploy BRANCHE -> recette
//   (+fix-loop) -> STOP à recette_ok (branche validée). Le **merge vers main N'est PAS** dans cette passe :
//   il se fait UNIQUEMENT à la fin, à l'accept, quand la feature est validée de bout en bout
//   (recette + non-reg + demo + accept). Bail-out (needs_human) sur tout échec.
// Déploie/teste la BRANCHE (Replay CODE_BRANCH=<branch>), pas main.
// Lancer : Workflow({ scriptPath:'~/.claude/workflows/run-ticket-full-auto.js',
//   args: { ticket:'SAMPLE-APPS-1', epic:'SAMPLE-APPS', prefix:'SAMPLE', repoName:'app-repo', branch:'feat/…' } })
export const meta = {
  name: 'run-ticket-full-auto',
  description: "Pipeline SDLC AUTO sur la branche du ticket (intégration) : review -> deploy BRANCHE -> recette (+fix-loop) -> stop recette_ok. Ne merge PAS main (merge = accept final).",
  phases: [
    { title: 'Prepare' },
    { title: 'Review' },
    { title: 'Deploy branche' },
    { title: 'Recette' },
  ],
}

const TICKET = (args && args.ticket) || 'SAMPLE-APPS-1'
const EPIC = (args && args.epic) || 'SAMPLE-APPS'
const PREFIX = (args && args.prefix) || 'SAMPLE'
const REPO_NAME = (args && args.repoName) || 'app-repo'
const REPO = (args && args.repo) || '<workspace>/app-repo'
const SDLC_ROOT = (args && args.sdlcRoot) || '<workspace>/sample-proj-sdlc-local'
const STORY = `${SDLC_ROOT}/${EPIC}/stories/${TICKET}`
const BRANCH = (args && args.branch) || `feat/${TICKET}`
const REF = (args && args.target) || 'main'             // branche de référence (comparaison review only)
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
const WS = { type: 'object', required: ['worktree'], properties: {
  worktree: { type: 'string' }, additionalDirectories: { type: 'array', items: { type: 'string' } },
  projectSkills: { type: 'array', items: { type: 'string' } } } }

const prepPrompt = () => `Prépare la **bulle scopée** du ticket **${TICKET}**. Exécute en Bash :
\`sdlc --project ${PREFIX} workspace ${TICKET} --branch ${BRANCH}\`
→ crée le worktree isolé + \`.claude/settings.json\` + \`scratch/\` + symlink des skills projet. Renvoie STRICTEMENT le JSON : worktree = \`.worktrees["${REPO_NAME}"]\`, additionalDirectories, projectSkills. Ne fais RIEN d'autre.`

const reviewPrompt = () => `Story SDLC **${TICKET}** (${WORKREPO}). Review le diff de ${BRANCH} vs ${REF} contre les INVARIANTS de ${STORY}/spec-tech.md (+ critères ${STORY}/spec-func.md). Diff: \`git -C ${WORKREPO} diff ${REF}...${BRANCH}\`. Vérifie chaque invariant (preuve), cherche bugs/régressions/fuites. Écris ${STORY}/review.md **en JOURNAL HORODATÉ, le plus récent en TÊTE** (prepend, n'écrase pas). Ne modifie PAS le code. **Transition dictée par l'orchestration — si conforme** : \`sdlc --project ${PREFIX} set-status ${TICKET} reviewed\`. Dernier message = JSON {conform, note, violations}.`

const deployBranchPrompt = () => `Story SDLC **${TICKET}**. Déploie la **BRANCHE ${BRANCH}** de ${WORKREPO} sur l'env d'INTÉGRATION (jamais main). Lis \`sdlc --project ${PREFIX} config\` → \`.deploy.${REPO_NAME}\` + charge les skills \`deploy-jenkins\` + \`agent-resilience\`. **AVANT de déclencher** : s'il existe déjà un build CI **récent/en cours pour le commit de ${BRANCH}**, **SUIS-LE** ; sinon Replay \`CODE_BRANCH=${BRANCH}\`. CI SUCCESS → CD → **santé** /actuator/health + version. \`curl -s -n\`, jamais \`-L\` ; jamais de secret ; scripts temp dans le **scratch de la bulle**, jamais /tmp. Sur échec/ambiguïté -> {ok:false, note} (pas de forçage). Écris ${STORY}/deploy.md **en JOURNAL HORODATÉ, récent en tête**. **Transition — si succès** : \`sdlc --project ${PREFIX} set-status ${TICKET} deployed\`. Dernier message = JSON {ok, version, note}.`

const recettePrompt = () => `Story SDLC **${TICKET}**. Recette sur la **branche déployée** vs les critères de ${STORY}/spec-func.md. Backend -> API ; UI -> Playwright MCP. Anti-flaky: 3x. Charge \`agent-resilience\` (scratch dans la bulle, pas /tmp ; filtre les sorties). Sur KO -> bundle repro ${STORY}/repro/. Écris ${STORY}/acceptance.md **en JOURNAL HORODATÉ, récent en tête**. **Transition — si tout passe** : \`sdlc --project ${PREFIX} set-status ${TICKET} recette_ok\`. Dernier message = JSON {pass, repro, flaky, failed}.`

const fixPrompt = (repro) => `Story SDLC **${TICKET}**. Recette KO. **Transitions dictées** : au démarrage \`sdlc --project ${PREFIX} set-status ${TICKET} implemented\` ; après commit \`... set-status ${TICKET} reviewed\`. Monte l’env local, rejoue le repro (${repro}), corrige sans casser les invariants, re-run local jusqu'au vert, commit + push **sur la MÊME branche ${BRANCH}** (worktree ${WORKREPO}). Écris ${STORY}/implement.md **en JOURNAL HORODATÉ, récent en tête**. Scripts temp dans le scratch de la bulle, jamais /tmp. Dernier message = JSON {fixed, root_cause, commit}.`

// ── Prepare : bulle scopée (worktree isolé + settings + scratch + skills projet) ──
phase('Prepare')
const prep = await agent(prepPrompt(), { agentType: 'general-purpose', schema: WS, label: `prepare:${TICKET}`, phase: 'Prepare' })
if (prep && prep.worktree) { WORKREPO = prep.worktree; log(`Bulle prête — worktree isolé: ${WORKREPO}`) }
else log(`Prepare KO -> repli sur ${WORKREPO} (working tree partagé)`)

// ── Review (diff branche vs ref, ne modifie rien) ──
phase('Review')
const rev = await agent(reviewPrompt(), { agentType: 'reviewer', schema: REVIEW, label: `review:${TICKET}`, phase: 'Review' })
if (!rev || !rev.conform) return { stopped_at: 'review', reason: 'needs_human', review: rev }
log('Review conforme ✅')

// ── Deploy BRANCHE (jamais main) ──
phase('Deploy branche')
let dep = await agent(deployBranchPrompt(), { agentType: 'deployer', schema: DEPLOY, label: `deploy:${TICKET}`, phase: 'Deploy branche' })
if (!dep || !dep.ok) return { stopped_at: 'deploy', reason: 'needs_human', deploy: dep }

// ── Recette sur la branche déployée (+ fix-loop, tout sur la branche) ──
phase('Recette')
let tries = 0
while (true) {
  const rec = await agent(recettePrompt(), { agentType: 'recetteur', schema: RECETTE, label: `recette:${TICKET}`, phase: 'Recette' })
  if (rec && rec.pass) { log('Recette verte ✅'); break }
  if (!rec || rec.flaky || tries >= MAX_FIX) return { stopped_at: 'recette', reason: 'needs_human', recette: rec }
  tries++
  log(`Recette KO -> fix-loop ${tries}/${MAX_FIX} (même branche ${BRANCH})`)
  await agent(fixPrompt(rec.repro), { agentType: 'fixer', schema: FIX, label: `fix:${TICKET}`, phase: 'Recette' })
  await agent(deployBranchPrompt(), { agentType: 'deployer', schema: DEPLOY, label: `redeploy:${TICKET}`, phase: 'Recette' })
}

// ── STOP à recette_ok : la BRANCHE est validée. Le merge vers main se fait à l'ACCEPT FINAL ──
// (feature validée de bout en bout : + non-reg + demo + accept humain). Voir run-ticket-downstream / accept.
log(`✅ ${TICKET} : branche ${BRANCH} déployée + recettée (${dep.version}). Merge main = à l'accept final.`)
return { stopped_at: 'recette', reason: 'branch_validated', version: dep.version, branch: BRANCH, review: rev }
