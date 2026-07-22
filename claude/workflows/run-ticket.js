// run-ticket — pipeline autonome d'un ticket SDLC (Harry).
// Calque sample-proj-sdlc-local/tooling/sdlc/orchestrator.py (logique de référence testée en stub).
// Lancer : Workflow({ name: 'run-ticket', args: 'SAMPLE-GATES-1' })   // ID seul suffit (epic/repo/chemins auto-résolus)
//     ou : Workflow({ name: 'run-ticket', args: { ticket:'SAMPLE-GATES-1', epic, prefix, repo, ... } })
export const meta = {
  name: 'run-ticket',
  description: "Pipeline autonome d'un ticket SDLC : reviewer -> deployer -> recette (+ fix-loop), gates + escalation",
  phases: [
    { title: 'Prepare' },
    { title: 'Review' },
    { title: 'Deploy' },
    { title: 'Recette' },
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
// valeurs faibles — écrasées par la résolution de la phase Prepare (via `sdlc config`/`get`)
let EPIC = A.epic
let REPO_NAME = A.repoName
let REPO = A.repo
let SDLC_ROOT = A.sdlcRoot
let BRANCH = A.branch || `feat/${TICKET}`
let ESC = A.escalation
let STORY = ''            // calculé après résolution Prepare
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

const WS = { type: 'object', required: ['resolved'], properties: {
  resolved: { type: 'boolean' }, worktree: { type: 'string' },
  epic: { type: 'string' }, repoName: { type: 'string' }, repo: { type: 'string' },
  sdlcRoot: { type: 'string' }, branch: { type: 'string' }, escalation: { type: 'object' },
  additionalDirectories: { type: 'array', items: { type: 'string' } },
  projectSkills: { type: 'array', items: { type: 'string' } }, note: { type: 'string' } } }

const prepPrompt = () => `Prépare la **bulle scopée** du ticket **${TICKET}** (préfixe projet **${PREFIX}**).
1. **Résous la config** en Bash :
   - \`sdlc --project ${PREFIX} get ${TICKET}\` → si le ticket est introuvable (erreur/"introuvable"), renvoie \`{"resolved":false,"note":"ticket ${TICKET} introuvable"}\` et NE crée RIEN. Sinon récupère \`epic\`, la 1re entrée de \`repos[]\` (= repoName) et \`branch\` (sinon \`feat/${TICKET}\`).
   - \`sdlc --project ${PREFIX} config\` → \`workspace\` (= sdlcRoot), le chemin du repo via \`repos[repoName]\` (= repo), \`escalation\`.
2. **Crée la bulle** : \`sdlc --project ${PREFIX} workspace ${TICKET} --branch <branch résolue>\` → worktree isolé + \`.claude/settings.json\` (additionalDirectories = worktrees+brain+data) + symlink des skills projet.
Renvoie STRICTEMENT le JSON : \`{resolved:true, worktree (= .worktrees[repoName]), epic, repoName, repo, sdlcRoot, branch, escalation, additionalDirectories, projectSkills}\`. Ne fais RIEN d'autre.`

const reviewPrompt = () => `Story SDLC **${TICKET}** (${WORKREPO}). Review le diff de la branche vs main contre les INVARIANTS du spec-tech.
Lis: ${STORY}/spec-tech.md (invariants = ta checklist) + ${STORY}/spec-func.md (critères).
Diff: \`git -C ${WORKREPO} diff main...HEAD\`. Vérifie CHAQUE invariant (preuve dans le diff), cherche bugs/régressions/fuites. Écris ${STORY}/review.md. Ne modifie PAS le code.
**Transition dictée par l'orchestration — si (et seulement si) conforme** : \`sdlc --project ${PREFIX} set-status ${TICKET} reviewed\`. Ne décide d'aucune autre transition.
Dernier message = JSON {conform, note, violations}.`

const deployPrompt = () => `Story SDLC **${TICKET}**. Déploie ${WORKREPO} branche courante **en DEV UNIQUEMENT** (namespace dev app-ns, values dev helm ; JAMAIS prod). Connais Jenkins/kubectl/Replay/gitops. Vérifie la santé (/actuator/health). **Sécurité : si l'env dev n'est pas clairement prêt, ou si une action est ambiguë/risquée/irréversible, NE déploie PAS → retourne {ok:false, note:"raison"} pour escalade humaine.** Écris ${STORY}/deploy.md. **Transition dictée par l'orchestration — si le déploiement réussit** : \`sdlc --project ${PREFIX} set-status ${TICKET} deployed\`. Dernier message = JSON {ok, version, note}.`

const recettePrompt = () => `Story SDLC **${TICKET}**. Recette sur l'env déployé vs les critères d'acceptation de ${STORY}/spec-func.md. Feature backend -> pilote l'API ; UI -> Playwright MCP. Anti-flaky: rejoue 3x. Sur KO produit un bundle repro dans ${STORY}/repro/. Écris ${STORY}/acceptance.md. **Transition dictée par l'orchestration — si tous les critères passent** : \`sdlc --project ${PREFIX} set-status ${TICKET} recette_ok\`. Dernier message = JSON {pass, repro, flaky, failed}.`

const fixPrompt = (repro) => `Story SDLC **${TICKET}**. Recette KO. **Transitions dictées par l'orchestration** : au démarrage \`sdlc --project ${PREFIX} set-status ${TICKET} implemented\` (retour dev) ; après le commit \`sdlc --project ${PREFIX} set-status ${TICKET} reviewed\`. Monte l’env local du projet, rejoue le bundle repro (${repro}), corrige le code sans casser les invariants (${STORY}/spec-tech.md), re-run en local jusqu'au vert, commit sur la branche. Dernier message = JSON {fixed, root_cause, commit}.`

// ── PREPARE : résout la config projet (sdlc config/get) + matérialise la bulle scopée ──
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
ESC = ESC || prep.escalation || { review: 'auto', deploy: 'human-confirm', recette: 'auto-then-human' }
WORKREPO = prep.worktree || REPO
STORY = `${SDLC_ROOT}/${EPIC}/stories/${TICKET}`
// garde-fou anti-placeholder : ne jamais avancer sur des valeurs fictives
if (!EPIC || !SDLC_ROOT || !REPO || `${EPIC}${SDLC_ROOT}${REPO}`.includes('<workspace>')) {
  log('Prepare : config non résolue (placeholders restants) -> STOP (humain)')
  return { stopped_at: 'prepare', reason: 'needs_human', detail: 'config non résolue (placeholders)', prepare: prep }
}
log(`Bulle prête — ${EPIC}/${TICKET} @ ${WORKREPO}${(prep.projectSkills||[]).length ? ' | skills: '+prep.projectSkills.join(',') : ''}`)

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
