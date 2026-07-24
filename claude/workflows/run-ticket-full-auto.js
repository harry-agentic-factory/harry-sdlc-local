// run-ticket-full-auto — ALIAS de run-ticket avec la REVIEW en AUTO (pas de gate review humaine).
// TOUT le code est commun (run-ticket.js) : deploy branche direct -> recette -> VALIDATION HUMAINE -> promote.
// Seule différence : `review: 'auto'` (le reviewer agent seul, aucune approbation humaine de la review).
// Pour promouvoir (après ta validation de la recette) : relance avec { promote: true } (délégué à run-ticket).
// Lancer : Workflow({ scriptPath:'~/.claude/workflows/run-ticket-full-auto.js',
//   args: { ticket:'HIA-ENROL-1', epic:'HIA-ENROL', prefix:'HIA', repoName:'back-hia', branch:'feat/…' } })
export const meta = {
  name: 'run-ticket-full-auto',
  description: "Alias de run-ticket avec review AUTO (seule diff = pas de gate review humaine). Reste identique : deploy branche -> recette -> validation humaine -> promote.",
  phases: [
    { title: 'run-ticket (review=auto)' },
  ],
}

// Chemin du code commun (install standard = symlink ~/.claude/workflows ; source = harry-sdlc-local).
const RUN_TICKET = '/Users/anisbessa/.claude/workflows/run-ticket.js'

// Délégation : même pipeline, review forcée en AUTO. Le résultat (await_validation / promote / done) remonte tel quel.
return await workflow({ scriptPath: RUN_TICKET }, { ...(args || {}), review: 'auto' })
