// run-ticket — pipeline autonome d'un ticket SDLC (Harry).
// Calque sample-proj-sdlc-local/tooling/sdlc/orchestrator.py (logique de référence testée en stub).
// Lancer : Workflow({ name: 'run-ticket', args: { ticket: 'SAMPLE-APPS-1', epic: 'SAMPLE-APPS' } })
// Args utiles : `base` (branche d'intégration de la story : `main` par défaut, `origin/epic/<EPIC>` en trunk
// d'épic) ; l'infra n'est JAMAIS en dur ici : le deployer résout la cible via `sdlc deploy-target <repo>
// --env dev|integration` (dev = branche pré-merge, integration = post-merge) et applique le skill rendu.
// PORTÉE : boucle PRÉ-MERGE, monde du développeur. Le merge sur main, la CI/CD et la recette
// classiques sont un autre univers — le workflow s'arrête sur la recette et rend la main.
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
// Le runtime peut passer `args` en OBJET ou en CHAÎNE JSON — normaliser en objet (sinon args.X = undefined -> défauts SAMPLE).
const A = (typeof args === 'string' ? (() => { try { return JSON.parse(args) } catch { return {} } })() : (args || {}))
const TICKET = A.ticket || 'SAMPLE-APPS-1'
const EPIC = A.epic || 'SAMPLE-APPS'
const PREFIX = A.prefix || 'SAMPLE'
const REPO_NAME = A.repoName || 'app-repo'
const REPO = A.repo || '<workspace>/app-repo'
const BRANCH = A.branch || `feat/${TICKET}`
const BASE = A.base || 'main'                       // diff de review + cible du merge (promote)
const BASE_BRANCH = BASE.replace(/^origin\//, '')   // nom de branche sans remote, pour la MR
const SDLC_ROOT = A.sdlcRoot || '<workspace>/sample-proj-sdlc-local'
const STORY = `${SDLC_ROOT}/${EPIC}/stories/${TICKET}`
const ESC = A.escalation || { review: 'auto', deploy: 'auto', recette: 'auto', promote: 'human' }
const REVIEW_HUMAN = (((A.review || ESC.review) || 'human') === 'human')  // option : gate review humaine (défaut) vs review auto
const REVIEW_OK = !!A.reviewOk // review humaine déjà approuvée -> on reprend directement au deploy branche
const FIX_FROM = A.fixFrom || null   // chemin d'un bundle repro -> RÉ-ENTRÉE directe dans la fix-loop
                                     // (recette MANUELLE de la session KO : on repart du FIXER,
                                     //  pas du début — review et premier deploy sont déjà faits)
const PROMOTE = !!A.promote   // true = phase PROMOTE (après validation humaine de la recette de branche)
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

const reviewPrompt = () => `Story SDLC **${TICKET}** (${WORKREPO}). Review le diff de la branche vs ${BASE} contre les INVARIANTS du spec-tech.
Lis: ${STORY}/spec-tech.md (invariants = ta checklist) + ${STORY}/spec-func.md (critères).
Diff: \`git -C ${WORKREPO} diff ${BASE}...HEAD\`. Vérifie CHAQUE invariant (preuve dans le diff), cherche bugs/régressions/fuites. Écris ${STORY}/review.md. Ne modifie PAS le code.
**Transition dictée par l'orchestration — si (et seulement si) conforme** : \`sdlc --project ${PREFIX} set-status ${TICKET} reviewed\`. Ne décide d'aucune autre transition.
Dernier message = JSON {conform, note, violations}.`

const deployPrompt = () => `Story SDLC **${TICKET}**. **DÉPLOIE LA BRANCHE \`${BRANCH}\` sur son environnement de test pré-merge.**
Cible = \`sdlc --project ${PREFIX} deploy-target ${REPO_NAME} --env dev\` : charge le **skill** qu'elle rend et suis-le (méthode, santé, preuve que le code déployé = HEAD de \`${BRANCH}\`, rollback). Aucune infra en dur : Jenkins, docker local ou autre, c'est le manifest qui dit. **NE touche PAS à ${BASE_BRANCH} ni à main, NE merge PAS** — on déploie la branche pour la recetter. **Sécurité : pas de cible \`dev\`, env pas prêt, cible = production, ou action ambiguë/risquée/irréversible ⇒ NE déploie PAS → {ok:false, note:"raison"}.** Écris ${STORY}/deploy.md. **Transition dictée par l'orchestration — si le déploiement branche réussit** : \`sdlc --project ${PREFIX} set-status ${TICKET} deployed\`. Dernier message = JSON {ok, version, note}.`

const promotePrompt = () => `Story SDLC **${TICKET}** — **PROMOTE**. Recette de branche validée par l'humain.
1) **Merge** la MR/PR de la branche \`${BRANCH}\` → \`${BASE_BRANCH}\` (CLI de l'hébergeur du repo : gh / glab / az ; **TA propre MR** ; **jamais** de push direct).
2) **Déploie \`${BASE_BRANCH}\`** sur la cible post-merge : \`sdlc --project ${PREFIX} deploy-target ${REPO_NAME} --env integration\` → applique le skill rendu, suis jusqu'au bout, **vérifie la version déployée + santé**. Pas de cible \`integration\` ⇒ c'est une gate humaine voulue : {ok:false, note:"pas d'env integration"}.
Écris ${STORY}/deploy.md (section « promote »). Dernier message = JSON {ok, version, note}.
**Portée** : merger et redéployer, rien d'autre. La mise en production, sa CI/CD et sa recette sont un autre univers — ce n'est pas ce loop qui les pilote.`

const recettePrompt = () => `Story SDLC **${TICKET}**. Recette sur l'env déployé vs les critères d'acceptation de ${STORY}/spec-func.md. Cible + méthode = \`sdlc --project ${PREFIX} config\` → \`recette.${REPO_NAME}\` (outil, skill projet, santé) et \`deploy.${REPO_NAME}.environments.dev\` ; vérifie d'abord que la version déployée = HEAD de \`${BRANCH}\`. Feature backend -> pilote l'API ; UI -> Playwright MCP ; CLI -> commandes sur la cible. Anti-flaky: rejoue 3x. Sur KO produit un bundle repro dans ${STORY}/repro/. Écris ${STORY}/acceptance.md. **Transition dictée par l'orchestration — si tous les critères passent** : \`sdlc --project ${PREFIX} set-status ${TICKET} recette_ok\`. Dernier message = JSON {pass, repro, flaky, failed}.`

const fixPrompt = (repro) => `Story SDLC **${TICKET}**. Recette KO. **Transitions dictées par l'orchestration** : au démarrage \`sdlc --project ${PREFIX} set-status ${TICKET} implemented\` (retour dev) ; après le commit \`sdlc --project ${PREFIX} set-status ${TICKET} reviewed\`. Worktree : ${WORKREPO}. Monte l’env local du projet (même cible que \`sdlc --project ${PREFIX} deploy-target ${REPO_NAME} --env dev\`), rejoue le bundle repro (${repro}), corrige le code sans casser les invariants (${STORY}/spec-tech.md), re-run en local jusqu'au vert, commit sur la branche. Dernier message = JSON {fixed, root_cause, commit}.`

// ── PHASE PROMOTE — après validation humaine de la recette de branche (args.promote=true).
//    Merger sur la branche de base, la redéployer, puis REJOUER LA MÊME RECETTE dessus. Rien d'autre :
//    la mise en prod et la recette classique vivent hors de ce loop.
if (PROMOTE) {
  phase('Promote')
  log(`Validation humaine reçue -> PROMOTE ${TICKET} : merge ${BRANCH} -> ${BASE_BRANCH}, puis on rejoue la recette dessus`)
  const prom = await agent(promotePrompt(), { agentType: 'deployer', schema: DEPLOY, label: `promote:${TICKET}`, phase: 'Promote' })
  if (!prom || !prom.ok) return { stopped_at: 'promote', reason: 'needs_human', promote: prom }
  log(`Merge + déploiement de ${BASE_BRANCH} OK (${prom.version}) -> recette dessus`)
  const recMain = await agent(recettePrompt(), { agentType: 'recetteur', schema: RECETTE, label: `recette-${BASE_BRANCH}:${TICKET}`, phase: 'Promote' })
  if (!recMain || !recMain.pass) return { stopped_at: 'promote', reason: 'needs_human', promote: prom, recette: recMain }
  log(`Recette OK sur ${BASE_BRANCH} ✅ — le loop a terminé son travail.`)
  return { stopped_at: 'promote', reason: 'done', promote: prom, recette: recMain }
}

// ── PHASE A — PREPARE : matérialise la bulle scopée (worktree isolé + settings + skills projet) ──
phase('Prepare')
const prep = await agent(prepPrompt(), { agentType: 'general-purpose', schema: WS, label: `prepare:${TICKET}`, phase: 'Prepare' })
if (prep && prep.worktree) { WORKREPO = prep.worktree; log(`Bulle prête — worktree isolé: ${WORKREPO}${(prep.projectSkills||[]).length ? ' | skills projet: '+prep.projectSkills.join(',') : ''}`) }
else log(`Prepare KO -> repli sur ${WORKREPO} (working tree partagé)`)

// ── PHASE A — REVIEW : option `review` = 'human' (gate, défaut) | 'auto'. Sautée si reprise après approbation ──
let rev = null
if (!REVIEW_OK && !FIX_FROM) {
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

// ── DEPLOY BRANCHE — cible = `deploy-target --env dev` (pré-merge ; JAMAIS la branche de base, JAMAIS la prod).
//    Le deployer applique le skill rendu et refuse si la cible configurée est la production.
if (!FIX_FROM) {
  phase('Deploy')
  const dep = await agent(deployPrompt(), { agentType: 'deployer', schema: DEPLOY, label: `deploy:${TICKET}`, phase: 'Deploy' })
  if (!dep || !dep.ok) return { stopped_at: 'deploy', reason: 'needs_human', deploy: dep, review: rev }
}

phase('Recette')
let tries = 0
if (FIX_FROM) {
  // Boucle externe : la recette MANUELLE de la session a trouvé des bugs. On repart du FIXER avec son
  // bundle repro — c'est ça, le loop engineering : fixer -> deployer -> recetteur, autant de fois qu'il
  // faut, jusqu'à ce que le stock de bugs soit épuisé.
  log(`Ré-entrée fix-loop depuis la session (recette manuelle KO) — repro: ${FIX_FROM}`)
  await agent(fixPrompt(FIX_FROM), { agentType: 'fixer', schema: FIX, label: `fix:${TICKET}`, phase: 'Recette' })
  await agent(deployPrompt(), { agentType: 'deployer', schema: DEPLOY, label: `redeploy:${TICKET}`, phase: 'Recette' })
}
while (true) {
  const rec = await agent(recettePrompt(), { agentType: 'recetteur', schema: RECETTE, label: `recette:${TICKET}`, phase: 'Recette' })
  if (rec && rec.pass) { log(`Recette agent OK ✅ sur la BRANCHE déployée — un CANDIDAT, pas une conclusion. Reprends la main en session : RECETTE MANUELLE (UI et/ou API, assertions chiffrées). KO -> 1 item pm par bug + sdlc reject --to implemented + relance. OK -> validation humaine, puis relance avec {promote:true} : merge sur ${BASE_BRANCH} + on rejoue la recette dessus.`); return { stopped_at: 'recette', reason: 'await_validation', recette: rec } }
  if (!rec || rec.flaky || tries >= MAX_FIX) return { stopped_at: 'recette', reason: 'needs_human', recette: rec }
  tries++
  log(`Recette KO -> fix-loop ${tries}/${MAX_FIX}`)
  await agent(fixPrompt(rec.repro), { agentType: 'fixer', schema: FIX, label: `fix:${TICKET}`, phase: 'Recette' })
  await agent(deployPrompt(), { agentType: 'deployer', schema: DEPLOY, label: `redeploy:${TICKET}`, phase: 'Recette' })
}
