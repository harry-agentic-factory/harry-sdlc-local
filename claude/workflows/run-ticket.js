// run-ticket — pipeline autonome d'un ticket SDLC (Harry).
// Calque hia-sdlc/tooling/sdlc/orchestrator.py (logique de référence testée en stub).
// Lancer : Workflow({ name: 'run-ticket', args: { ticket: 'HIA-APPS-1', epic: 'HIA-APPS' } })
export const meta = {
  name: 'run-ticket',
  description: "Pipeline autonome d'un ticket SDLC : reviewer -> deployer -> recette (+ fix-loop), gates + escalation",
  phases: [
    { title: 'Review' },
    { title: 'Deploy' },
    { title: 'Recette' },
  ],
}

// ── paramètres ──
const TICKET = (args && args.ticket) || 'HIA-APPS-1'
const EPIC = (args && args.epic) || 'HIA-APPS'
const REPO = (args && args.repo) || '/Users/anisbessa/dev/workspace/hia/back-tenant'
const SDLC_ROOT = (args && args.sdlcRoot) || '/Users/anisbessa/dev/workspace/hia/hia-sdlc'
const STORY = `${SDLC_ROOT}/${EPIC}/stories/${TICKET}`
const ESC = (args && args.escalation) || { review: 'auto', deploy: 'human-confirm', recette: 'auto-then-human' }
const MAX_FIX = 2

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

const reviewPrompt = () => `Story SDLC **${TICKET}** (${REPO}). Review le diff de la branche vs main contre les INVARIANTS du spec-tech.
Lis: ${STORY}/spec-tech.md (invariants = ta checklist) + ${STORY}/spec-func.md (critères).
Diff: \`git -C ${REPO} diff main...HEAD\`. Vérifie CHAQUE invariant (preuve dans le diff), cherche bugs/régressions/fuites. Écris ${STORY}/review.md. Ne modifie PAS le code.
Dernier message = JSON {conform, note, violations}.`

const deployPrompt = () => `Story SDLC **${TICKET}**. Déploie ${REPO} branche courante **en DEV UNIQUEMENT** (namespace dev hia-tenant, values dev helm ; JAMAIS prod). Connais Jenkins/kubectl/Replay/gitops. Vérifie la santé (/actuator/health). **Sécurité : si l'env dev n'est pas clairement prêt, ou si une action est ambiguë/risquée/irréversible, NE déploie PAS → retourne {ok:false, note:"raison"} pour escalade humaine.** Écris ${STORY}/deploy.md. Dernier message = JSON {ok, version, note}.`

const recettePrompt = () => `Story SDLC **${TICKET}**. Recette sur l'env déployé vs les critères d'acceptation de ${STORY}/spec-func.md. Feature backend -> pilote l'API ; UI -> Playwright MCP. Anti-flaky: rejoue 3x. Sur KO produit un bundle repro dans ${STORY}/repro/. Écris ${STORY}/acceptance.md. Dernier message = JSON {pass, repro, flaky, failed}.`

const fixPrompt = (repro) => `Story SDLC **${TICKET}**. Recette KO. Monte local-dev, rejoue le bundle repro (${repro}), corrige le code sans casser les invariants (${STORY}/spec-tech.md), re-run en local jusqu'au vert, commit sur la branche. Dernier message = JSON {fixed, root_cause, commit}.`

// ── TRONÇON 1 : review -> deploy -> recette (+ fix-loop) ──
phase('Review')
const rev = await agent(reviewPrompt(), { agentType: 'reviewer', schema: REVIEW, label: `review:${TICKET}`, phase: 'Review' })
if (!rev || !rev.conform) {
  log(`Review NON conforme -> STOP (humain). Violations: ${rev ? (rev.violations || []).join(' | ') : 'agent KO'}`)
  return { stopped_at: 'review', reason: 'needs_human', review: rev }
}
log('Review conforme ✅')

phase('Deploy')
if (ESC.deploy === 'human-confirm') {
  log('Gate deploy = human-confirm (prod) -> STOP, en attente de ta validation')
  return { stopped_at: 'deploy', reason: 'needs_human', detail: 'confirm deploy', review: rev }
}
const dep = await agent(deployPrompt(), { agentType: 'deployer', schema: DEPLOY, label: `deploy:${TICKET}`, phase: 'Deploy' })
if (!dep || !dep.ok) return { stopped_at: 'deploy', reason: 'needs_human', deploy: dep, review: rev }

phase('Recette')
let tries = 0
while (true) {
  const rec = await agent(recettePrompt(), { agentType: 'recetteur', schema: RECETTE, label: `recette:${TICKET}`, phase: 'Recette' })
  if (rec && rec.pass) return { stopped_at: 'recette', reason: 'await_validation', recette: rec }
  if (!rec || rec.flaky || tries >= MAX_FIX) return { stopped_at: 'recette', reason: 'needs_human', recette: rec }
  tries++
  log(`Recette KO -> fix-loop ${tries}/${MAX_FIX}`)
  await agent(fixPrompt(rec.repro), { agentType: 'fixer', schema: FIX, label: `fix:${TICKET}`, phase: 'Recette' })
  await agent(deployPrompt(), { agentType: 'deployer', schema: DEPLOY, label: `redeploy:${TICKET}`, phase: 'Recette' })
}
