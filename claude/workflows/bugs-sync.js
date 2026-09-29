// bugs-sync — instruct the bug cards of an issue tracker: one investigation per card, then one
// consolidation pass that writes the review /bugs-review walks the human through.
// Launched by /bugs-sync (which pulls the board and reads each card with the `tracker` CLI first):
//   Workflow({ scriptPath: '~/.claude/workflows/bugs-sync.js',
//              args: { prefix, date, trackerDir, cards: [{ card, shortLink, name, url, list, labels, raw }] } })
// It creates NOTHING in the SDLC: epics and stories are born after the human review, not here.
export const meta = {
  name: 'bugs-sync',
  description: 'Investigate each new bug card in parallel, then consolidate the files into one review for the human',
  phases: [
    { title: 'Symptom', detail: 'strip the analysis already written on the card, keep what was observed' },
    { title: 'Investigate', detail: 'one investigator per card, file written under _tracker/cards/' },
    { title: 'Consolidate', detail: 'cross-card evidence, questions capped, review-bugs.md' },
  ],
}

const A = (typeof args === 'string' ? (() => { try { return JSON.parse(args) } catch { return {} } })() : (args || {}))
const PREFIX = A.prefix
const DATE = A.date                      // YYYY-MM-DD, stamped by the caller (no clock in a workflow)
const DIR = A.trackerDir                 // <workspace>/_tracker
const CARDS = A.cards || []
const MAX_PARALLEL = A.maxParallel || 5
if (!PREFIX || !DATE || !DIR) throw new Error('args.prefix, args.date and args.trackerDir are required')
if (!CARDS.length) return { review: null, cards: [], note: 'no card to instruct' }

const REVIEW_DIR = `${DIR}/reviews/${DATE}`
const fichePath = (c) => `${DIR}/cards/${c.shortLink}/fiche.md`

const SYMPTOM = { type: 'object', required: ['hasObservableFacts', 'symptom'], properties: {
  hasObservableFacts: { type: 'boolean' },
  symptom: { type: 'string', description: 'what was observed: who, when, which screen or call, expected vs actual' },
  identifiers: { type: 'array', items: { type: 'string' }, description: 'real ids quoted by the report: account, tenant, timestamp, reference' },
  stripped: { type: 'string', description: 'one line: what analysis was removed, if any' } } }

const FICHE = { type: 'object', required: ['summary', 'cause', 'proofLevel', 'reproduced', 'fix', 'questions'], properties: {
  summary: { type: 'string', description: 'at most 5 lines, French' },
  cause: { type: 'string', description: 'the cause, or "non établie"' },
  proofLevel: { type: 'string', enum: ['mesuré', 'lu-dans-le-code', 'inféré', 'non-établi'] },
  reproduced: { type: 'string', enum: ['oui', 'non', 'non-tenté', 'impossible'] },
  workaround: { type: 'string' },
  fix: { type: 'object', properties: {
    proposal: { type: 'string' },
    repos: { type: 'array', items: { type: 'string' } },
    files: { type: 'array', items: { type: 'string' } } } },
  alreadyFixed: { type: 'string', description: 'if a deployed change already addresses it: which version/commit, else empty' },
  questions: { type: 'array', items: { type: 'object', required: ['question', 'default'], properties: {
    question: { type: 'string' }, default: { type: 'string', description: 'decision applied if the human does not answer' } } } },
  limitations: { type: 'array', items: { type: 'string' } } } }

const REVIEW = { type: 'object', required: ['review', 'cards'], properties: {
  review: { type: 'string', description: 'path of review-bugs.md' },
  cards: { type: 'array', items: { type: 'object', required: ['shortLink', 'id', 'severity', 'line'], properties: {
    shortLink: { type: 'string' }, id: { type: 'string', description: 'B<n> or M<n>' },
    severity: { type: 'string', enum: ['bloquant', 'majeur', 'mineur'] },
    line: { type: 'string', description: 'one-line recap' },
    module: { type: 'string' }, amended: { type: 'boolean' } } } },
  crossCard: { type: 'array', items: { type: 'string' }, description: 'evidence moved from one card to another' },
  grouping: { type: 'array', items: { type: 'object', properties: {
    repo: { type: 'string' }, cards: { type: 'array', items: { type: 'string' } } } } } } }

log(`${CARDS.length} card(s) to instruct, ${MAX_PARALLEL} investigations at a time at most`)

// Symptom -> investigation, per card, no barrier. The concurrency cap of the runtime is higher than what
// the environment under investigation should take, so cards are processed in waves of MAX_PARALLEL.
const results = []
for (let i = 0; i < CARDS.length; i += MAX_PARALLEL) {
  const wave = CARDS.slice(i, i + MAX_PARALLEL)
  const out = await pipeline(wave,
    (c) => agent(
      `Tu prépares le signalement d'un bug pour un investigateur. Voici la carte brute du tracker (JSON) :\n\n` +
      `${JSON.stringify({ name: c.name, list: c.list, labels: c.labels, ...c.raw })}\n\n` +
      `Extrais le SYMPTÔME, pas l'analyse. Garde ce qui a été observé : qui, quand, sur quel écran ou quel appel, ` +
      `ce qui était attendu, ce qui s'est produit, les identifiants réels (compte, tenant, horodatage, référence). ` +
      `RETIRE toute cause supposée, tout correctif envisagé, tout numéro de ligne ou chemin de code, tout ` +
      `rapprochement avec une autre carte, toute hypothèse — même quand la carte dit qu'elle « tranche ». ` +
      `Un investigateur qui reçoit l'analyse la recopie et rend un écho au lieu d'une enquête. ` +
      `Si la carte ne contient aucun fait observable, hasObservableFacts=false.`,
      { label: `symptom:${c.shortLink}`, phase: 'Symptom', schema: SYMPTOM, effort: 'low' }),
    (s, c) => {
      if (!s || !s.hasObservableFacts) {
        return { shortLink: c.shortLink, card: c, symptom: s, fiche: null,
          skipped: 'aucun fait observable sur la carte : à retourner au rapporteur' }
      }
      return agent(
        `Projet : ${PREFIX} (résous tes accès avec \`sdlc --project ${PREFIX} config\`). Rapport final en français.\n\n` +
        `Symptôme signalé (faits observés seulement ; l'analyse de la carte a été retirée exprès, établis la cause toi-même) :\n` +
        `${s.symptom}\n\nIdentifiants cités : ${(s.identifiers || []).join(', ') || 'aucun'}\n` +
        `Carte : ${c.url} — « ${c.name} »\n\n` +
        `Ce qu'il faut établir :\n` +
        `1. Le constat réel (données stockées, réponses d'API, code à la version DÉPLOYÉE), avec le niveau de preuve de chaque fait.\n` +
        `2. La cause, ou « non établie » avec la mesure qui trancherait.\n` +
        `3. Si ça se reproduit sur la version déployée AUJOURD'HUI, et si un changement déjà déployé le corrige.\n` +
        `4. Un contournement pour débloquer l'humain maintenant, s'il en existe un.\n` +
        `5. Le correctif pressenti : repos et fichiers touchés. Toute affirmation sur son risque ou son impact cite son chemin de code ; sinon, ne l'écris pas.\n` +
        `6. Au plus 3 questions pour l'humain, chacune avec la décision appliquée par défaut s'il ne répond pas.\n\n` +
        `Écris le dossier complet dans ${fichePath(c)} (crée le dossier), sans aucun secret. ` +
        `Lecture seule sur la prod ; n'écris aucun correctif.`,
        { label: `investigate:${c.shortLink}`, phase: 'Investigate', agentType: 'investigator', schema: FICHE })
        .then((f) => f && ({ shortLink: c.shortLink, card: c, symptom: s, fiche: fichePath(c), ...f }))
    })
  results.push(...out.filter(Boolean))
  log(`wave ${i / MAX_PARALLEL + 1}: ${out.filter(Boolean).length}/${wave.length} card(s) instructed`)
}
const failed = CARDS.filter((c) => !results.find((r) => r.shortLink === c.shortLink)).map((c) => c.shortLink)
if (failed.length) log(`not instructed (agent died or skipped): ${failed.join(', ')}`)

// Barrier on purpose: evidence found while investigating one card often settles another one.
phase('Consolidate')
const consolidated = await agent(
  `Tu consolides l'instruction de ${results.length} bug(s) du projet ${PREFIX}, en une seule passe. Voici les résultats ` +
  `structurés (chaque fiche complète est dans le fichier indiqué par \`fiche\`) :\n\n${JSON.stringify(results.map((r) => ({
    shortLink: r.shortLink, name: r.card.name, url: r.card.url, labels: r.card.labels, fiche: r.fiche, skipped: r.skipped,
    summary: r.summary, cause: r.cause, proofLevel: r.proofLevel, reproduced: r.reproduced, workaround: r.workaround,
    fix: r.fix, alreadyFixed: r.alreadyFixed, questions: r.questions, limitations: r.limitations })))}\n\n` +
  `Travail :\n` +
  `1. **Preuves croisées** : lis les fiches ensemble. Une preuve trouvée pour une carte qui en concerne une autre remonte ` +
  `vers celle-ci : ajoute-la dans la fiche concernée, section « ## Consolidation », en citant sa source.\n` +
  `2. **Hiérarchie de preuve** : mesuré > lu-dans-le-code > inféré > absence d'observation. Une non-observation n'est pas ` +
  `une contradiction. Toute affirmation de risque ou d'impact qui ne cite ni mesure ni code est retirée de la fiche (note-le).\n` +
  `3. **Questions** : déduplique entre cartes, 3 au plus par carte, chacune avec son défaut.\n` +
  `4. **Regroupement** : propose un regroupement des correctifs par module (repo). C'est une suggestion : l'humain décide.\n` +
  `5. Écris ${REVIEW_DIR}/review-bugs.md, au format ci-dessous, puis rends le résumé structuré.\n\n` +
  '```markdown\n---\nkind: review\ngate: bugs\n' + `target: ${PREFIX}-BUG-${DATE.replace(/-/g, '')}\nversion: 1\ndate: ${DATE}\n` +
  '---\n# Revue des bugs — ' + DATE + '\n\n' +
  '| # | Gravité | Carte | Constat | Cause (preuve) | Recommandation | Module | Fiche |\n|---|---|---|---|---|---|---|---|\n' +
  '| B1 | bloquant | [<shortLink>](<url>) | … | … (lu-dans-le-code) | … | back-tenant | cards/<shortLink>/fiche.md |\n\n' +
  '## Questions\n### B1 — <shortLink>\n- Q1. <question> — défaut : <décision>\n\n' +
  '## Déjà corrigé / sans fait observable\n\n## Preuves croisées\n\n## Regroupement suggéré par module\n```\n\n' +
  `Ids : B<n> pour une carte au label « bloquant », M<n> pour les autres, numérotés dans l'ordre de gravité. ` +
  `Une carte déjà corrigée par un changement déployé reste dans le tableau, avec la recommandation « vérifier et clore ». ` +
  `Une carte sans fait observable va dans sa section, avec la recommandation « retourner au rapporteur ». Aucun secret.`,
  { label: 'consolidate', phase: 'Consolidate', schema: REVIEW })

return {
  review: consolidated ? consolidated.review : null,
  cards: results.map((r) => ({ shortLink: r.shortLink, card: r.card.card, fiche: r.fiche, skipped: r.skipped || null,
    cause: r.cause, proofLevel: r.proofLevel, questions: (r.questions || []).length })),
  consolidation: consolidated,
  failed,
}
