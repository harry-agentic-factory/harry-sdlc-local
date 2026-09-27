"""CLI `sdlc` — surface en ligne de commande de la façade (utilisée par les
commandes Harry et testable directement). Sortie JSON.

    python3 -m sdlc.cli create-epic SAMPLE-PROV "Provisioning depuis le produit"
    python3 -m sdlc.cli create-ticket SAMPLE-PROV SAMPLE-PROV-1 "API" --deps SAMPLE-PROV-2,SAMPLE-PROV-3 --repos app-repo
    python3 -m sdlc.cli get SAMPLE-PROV-1
    python3 -m sdlc.cli next SAMPLE-PROV
    python3 -m sdlc.cli set-status SAMPLE-PROV-1 spec_tech
    python3 -m sdlc.cli link SAMPLE-PROV-1 spec_tech SAMPLE-PROV/stories/SAMPLE-PROV-1/spec-tech.md
"""
from __future__ import annotations

import argparse
import dataclasses
import difflib
import json
import sys

from .config import current_project, load_config, resolve_deploy_target, resolve_workspace, resolved_manifest
from .board import NullBoard
from .service import Sdlc
from .workspace import Workspace
from .version import version_line


def _csv(v: str | None) -> list[str]:
    return [x for x in (v or "").split(",") if x]


def _resolve_cmd(token: str, commands: list[str]) -> tuple[str | None, str | None]:
    """Devine la sous-commande si la frappe n'est pas exacte : préfixe unique > fuzzy proche.
    Retourne (commande_résolue|None, message|None). Ambigu → (None, suggestion)."""
    pref = [c for c in commands if c.startswith(token)]
    if len(pref) == 1:
        return pref[0], f"sdlc: « {token} » → « {pref[0]} »"
    close = difflib.get_close_matches(token, commands, n=3, cutoff=0.6)
    if not pref and len(close) == 1:
        return close[0], f"sdlc: « {token} » → « {close[0]} »"
    cands = pref or close
    if cands:
        return None, f"commande « {token} » inconnue — voulais-tu : {', '.join(cands)} ?"
    return None, None


def _project_arg(argv: list[str]) -> str | None:
    for j, a in enumerate(argv):
        if a == "--project" and j + 1 < len(argv):
            return argv[j + 1]
        if a.startswith("--project="):
            return a.split("=", 1)[1]
    return None


def _known_ids(argv: list[str]) -> set[str]:
    """IDs de tickets + épics du workspace résolu (pour deviner un `sdlc <ID>` = `status <ID>`)."""
    try:
        tickets = Workspace(resolve_workspace(_project_arg(argv))).all_tickets()
        return {t.id for t in tickets} | {t.epic for t in tickets}
    except Exception:  # noqa: BLE001 — pas de workspace résoluble → pas de déduction
        return set()


def _autocorrect(argv: list[str] | None, commands: list[str]) -> list[str]:
    """Corrige la 1re sous-commande de argv. Non reconnue mais = ID de ticket/épic → défaut `status`.
    Ambigu → ValueError (message clair)."""
    src = list(sys.argv[1:] if argv is None else argv)
    i = 0
    while i < len(src):
        tok = src[i]
        if tok == "--project":
            i += 2; continue
        if tok.startswith("-"):
            i += 1; continue
        if tok not in commands:               # 1er positionnel non reconnu
            resolved, note = _resolve_cmd(tok, commands)
            if resolved:                       # faute de frappe sur une sous-commande
                print(note, file=sys.stderr)   # stdout reste du JSON pur
                src[i] = resolved
            elif note:
                raise ValueError(note)          # ambigu → main() renvoie l'erreur proprement
            elif tok in _known_ids(src):        # pas une commande, mais un ID connu → défaut `status`
                print(f"sdlc: « {tok} » → « status {tok} »", file=sys.stderr)
                src.insert(i, "status")
            # sinon : laisse argparse produire l'erreur « invalid choice »
        break                                   # ne touche qu'à la sous-commande
    return src


# Gate sub-commands: canonical name, gate, historical names kept as aliases (same handler), help.
_GATE_PARSERS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("validate-spec-func", "spec_func", ("validate-func",),
     "GATE fonctionnelle : spec_func→spec_func_validated (story OU épic). Exige --verdict signé par un humain."),
    ("validate-spec-tech", "spec_tech", ("validate-spec", "validate-tech"),
     "GATE technique : spec_tech→spec_validated (story OU épic). Exige --verdict signé par un humain."),
    ("validate-feature", "feature", ("validate-epic",),
     "GATE feature : spec_validated→feature_validated (épic entier, avant l'usine). Exige les verdicts signés "
     "du PO et du tech lead."),
)
_GATE_CMDS: dict[str, str] = {cmd: gate for name, gate, aliases, _ in _GATE_PARSERS for cmd in (name, *aliases)}


class _VersionAction(argparse.Action):
    """`--version`: computes the version line only when the option is given, then exits 0."""

    def __call__(self, parser, namespace, values, option_string=None):
        sys.stdout.write(version_line() + "\n")
        sys.stdout.flush()
        parser.exit(0)


def _sdlc(project: str | None) -> Sdlc:
    ws = resolve_workspace(project)
    return Sdlc(Workspace(ws), NullBoard())


def run(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(
        prog="sdlc",
        description="Façade SDLC Harry — état des tickets/épics, DAG, artefacts, worktrees. Sortie JSON.",
        epilog="Astuce : `sdlc <commande> -h` pour le détail d'une commande. "
               "Pipeline : create-epic → create-ticket → set-status (spec_func→[validate-spec-func]→spec_tech→"
               "[validate-spec-tech]→spec_validated→[validate-feature]→feature_validated→implemented→"
               "reviewed→deployed→recette_ok→accepted→done).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action=_VersionAction, nargs=0,
                   help="print the engine version and mode, then exit")
    p.add_argument("--project", default=None, help="préfixe projet (ex. SAMPLE) ; sinon workspace résolu par défaut")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<commande>",
                           title="commandes", help="(voir `sdlc <commande> -h`)")

    # --- backlog / stories ---
    a = sub.add_parser("create-epic", help="crée un épic")
    a.add_argument("epic", help="ID épic (ex. SAMPLE-PROV)"); a.add_argument("title", help="titre de l'épic")
    a = sub.add_parser("create-ticket", help="crée une story dans un épic (avec deps + repos)")
    a.add_argument("epic", help="ID épic parent"); a.add_argument("story", help="ID story (ex. SAMPLE-PROV-1)")
    a.add_argument("title", help="titre de la story")
    a.add_argument("--deps", help="stories dont elle dépend, séparées par des virgules")
    a.add_argument("--repos", help="repos touchés, séparés par des virgules")
    a = sub.add_parser("get", help="réhydrate un ticket (statut, repos, branche, artefacts)")
    a.add_argument("story", help="ID story")
    a = sub.add_parser("list", help="liste le backlog (option : filtrer par statut)")
    a.add_argument("--status", help="filtre statut (spec_func|spec_tech|implemented|reviewed|deployed|…)")
    a = sub.add_parser("next", help="prochain actionnable d'un épic (résolution du DAG)")
    a.add_argument("epic", help="ID épic")
    a = sub.add_parser("set-status", help="change le statut d'une story (transition d'orchestration)")
    a.add_argument("story", help="ID story")
    a.add_argument("status", help="spec_func|spec_func_validated|spec_tech|spec_validated|feature_validated|"
                   "implemented|reviewed|deployed|recette_ok|accepted|done")
    a = sub.add_parser("link", help="attache un artefact (doc) à une story")
    a.add_argument("story", help="ID story")
    a.add_argument("kind", help="type : prd|spec_func|spec_tech|implement|review|deploy|acceptance|demo|review_spec_func|…")
    a.add_argument("path", help="chemin du .md relatif au repo data du projet")

    # --- projets / config / maintenance ---
    a = sub.add_parser("migrate", help="applique les migrations de schéma du workspace")
    a.add_argument("--workspace", help="chemin workspace (sinon résolu depuis --project)")
    a = sub.add_parser("init-project", help="initialise un nouveau projet SDLC (repo data + config)")
    a.add_argument("prefix", help="préfixe projet (ex. SAMPLE)")
    a.add_argument("--path", required=True, help="chemin du repo data du projet")
    a.add_argument("--repos", help="repos de code, séparés par des virgules")
    a = sub.add_parser("register", help="enregistre un projet existant dans le registre")
    a.add_argument("prefix", help="préfixe projet"); a.add_argument("path", help="chemin du repo data")
    sub.add_parser("projects", help="liste les projets enregistrés")
    a = sub.add_parser("config", help="manifest résolu du projet (deploy/recette/credentials…)")
    a.add_argument("--raw", action="store_true", help="config brute non résolue")
    a = sub.add_parser("skills", help="skills matchés par la stack de chaque repo (repo → stack → skills)")
    a.add_argument("--repo", help="limiter à un repo (sinon tous)")
    a = sub.add_parser("status", help="statut exact d'un ticket/épic (état + artefacts + recaps agents)")
    a.add_argument("target", nargs="?", help="ID ticket ou épic (sinon : projet entier)")
    a = sub.add_parser("deploy-target",
                       help="résout un environnement LOGIQUE (dev = pré-merge, integration = post-merge) "
                            "en cible CONCRÈTE pour un repo. Le deployer appelle ça et ne devine rien.")
    a.add_argument("repo", help="nom du repo")
    a.add_argument("--env", required=True, choices=["dev", "integration"], help="environnement logique")

    a = sub.add_parser("journal", help="consigne un EVENEMENT DE RUN dans le journal d'une story "
                                       "(arret de workflow, reprise, decision d'orchestration) — "
                                       "pour que le fait ne vive pas QUE dans la conversation")
    a.add_argument("story", help="ID story")
    a.add_argument("--entry", required=True, help="le fait, en clair (jamais de secret)")
    a.add_argument("--by", default="harry", help="auteur (defaut: harry)")

    a = sub.add_parser("reject", help="rejette une story (gate) → route vers spec_func|spec_tech|implemented + note (journal)")
    a.add_argument("story", help="ID story")
    a.add_argument("--to", required=True, help="étape de retour : spec_func | spec_tech | implemented")
    a.add_argument("--note", required=True, help="raison du rejet (consignée dans journal.md)")
    a.add_argument("--by", default="humain", help="auteur de la décision (défaut: humain)")
    # --- spec and feature gates: the agent recommends, a human decides (verdict signed in /process-review) ---
    for name, _gate, aliases, gate_help in _GATE_PARSERS:
        a = sub.add_parser(name, aliases=list(aliases), help=gate_help)
        a.add_argument("target", help="ID story OU épic" if name != "validate-feature" else "ID épic (la feature)")
        a.add_argument("--verdict", action="append", metavar="<path>",
                       help="verdict signé par un humain (review-<gate>-verdict.md) ; OBLIGATOIRE. "
                            "validate-feature : un par rôle (po, techlead), répétable")
        a.add_argument("--review", help="revue de l'agent (review-<gate>.md) ; défaut : celle du verdict")

    # --- worktrees / workspace agent ---
    a = sub.add_parser("worktree", help="crée/assure un git worktree par repo pour une story")
    a.add_argument("story", help="ID story"); a.add_argument("--repo", help="limiter à un repo (sinon tous ceux du ticket)")
    a.add_argument("--branch", help="branche (sinon ticket.branch)"); a.add_argument("--base", help="branche de base")
    a = sub.add_parser("worktree-clean", help="nettoie le(s) worktree(s) d'une story")
    a.add_argument("story", help="ID story"); a.add_argument("--branch", help="branche"); a.add_argument("--ref", help="ref à conserver")
    a = sub.add_parser("workspace", help="construit le workspace isolé d'un agent pour une story")
    a.add_argument("story", help="ID story"); a.add_argument("--branch", help="branche")
    a.add_argument("--agent", help="rôle agent (deployer/reviewer/…) → injecte permissions.allow/deny du manifest")

    # --- post-mortem : items consignés au fil de l'eau (dette/learning/incident/sécu/brain) ---
    pm = sub.add_parser("post-mortem", aliases=["pm"],
                        help="items de post-mortem : consigne / statue / convertit (dette ou Brain)")
    pmsub = pm.add_subparsers(dest="pmcmd", required=True, metavar="<pm-cmd>")
    a = pmsub.add_parser("add", help="consigne un item (qui/epic/story + kind/sévérité/texte)")
    a.add_argument("--agent", required=True, help="qui consigne (reviewer|recetteur|deployer|fixer|dev|demo|human|<commande>)")
    a.add_argument("--kind", required=True, help="debt|learning|incident|security|brain")
    a.add_argument("--text", required=True, help="description (jamais de secret)")
    a.add_argument("--epic", help="ID épic concerné")
    a.add_argument("--story", help="ID story concernée")
    a.add_argument("--severity", default="medium", help="low|medium|high (défaut medium)")
    a = pmsub.add_parser("list", help="liste les items courants (filtrable)")
    a.add_argument("--epic"); a.add_argument("--story"); a.add_argument("--agent")
    a.add_argument("--kind"); a.add_argument("--status")
    a = pmsub.add_parser("show", help="affiche un item"); a.add_argument("id", help="ID item (PM-…)")
    a = pmsub.add_parser("status", help="statue sur un item (append d'un snapshot)")
    a.add_argument("id", help="ID item (PM-…)")
    a.add_argument("status", choices=["open", "triaged", "wontfix"], help="open|triaged|wontfix")
    a.add_argument("--target", help="id ticket / URL PR Brain (optionnel)")
    a = pmsub.add_parser("to-ticket", help="convertit l'item en story de dette dans un épic")
    a.add_argument("id", help="ID item (PM-…)")
    a.add_argument("--epic", required=True, help="épic dette cible (DEBT_EPIC)")
    a.add_argument("--repos", help="repos touchés, séparés par des virgules")
    a = pmsub.add_parser("to-brain", help="marque l'item pour le Brain + suggère l'entrée de propale")
    a.add_argument("id", help="ID item (PM-…)")

    # --- brain: read a git knowledge repo at a commit (sdlc.brain library) ---
    from .brain import cli as brain_cli
    brain_cli.add_parser(sub)
    # --- run workspace of an autonomous agent (sdlc.runws library) ---
    from .runws import cli as runws_cli
    runws_cli.add_parsers(sub)

    args = p.parse_args(_autocorrect(argv, list(sub.choices)))

    if args.cmd == "brain":
        return brain_cli.dispatch(args)
    if args.cmd in ("run", "doc", "clone"):  # never resolves a workspace before the library does
        return runws_cli.dispatch(args)

    if args.cmd == "migrate":
        from .migrations import apply_migrations
        ws = args.workspace or resolve_workspace(args.project)
        return apply_migrations(ws)
    if args.cmd == "init-project":
        from .project import init_project
        return init_project(args.prefix, args.path, _csv(args.repos))
    if args.cmd == "register":
        from .project import register_project
        return {"prefix": args.prefix, "registered": register_project(args.prefix, args.path)}
    if args.cmd == "projects":
        from .project import list_projects
        # `current` = projet déduit du CWD (lève l'ambiguïté quand plusieurs sont enregistrés).
        # `--project` explicite l'emporte s'il est fourni et connu.
        projects = list_projects()
        cur = args.project if args.project in projects else current_project()
        return {"projects": projects, "current": cur}
    if args.cmd == "config":
        if args.raw:
            return load_config(resolve_workspace(args.project))
        return resolved_manifest(args.project, with_brain_ref=True)
    if args.cmd == "skills":
        man = resolved_manifest(args.project)
        stacks = man.get("stacks", {})
        sbr = man.get("skillsByRepo", {})
        names = [args.repo] if args.repo else list(stacks.keys())
        return {"skills": {n: {"stack": stacks.get(n), "skills": sbr.get(n, [])} for n in names}}
    if args.cmd == "status":
        from .status_report import build_status
        return build_status(resolve_workspace(args.project), args.target)
    if args.cmd in ("post-mortem", "pm"):
        from .post_mortem import PostMortemStore
        store = PostMortemStore(resolve_workspace(args.project))
        if args.pmcmd == "add":
            item = store.add(agent=args.agent, kind=args.kind, text=args.text,
                             epic=args.epic, story=args.story, severity=args.severity)
            return {"id": item.id}
        if args.pmcmd == "list":
            return {"items": [dataclasses.asdict(i) for i in store.list(
                epic=args.epic, story=args.story, agent=args.agent,
                kind=args.kind, status=args.status)]}
        if args.pmcmd == "show":
            return dataclasses.asdict(store.get(args.id))
        if args.pmcmd == "status":
            return dataclasses.asdict(store.set_status(args.id, args.status, target=args.target))
        if args.pmcmd == "to-ticket":
            return store.to_ticket(args.id, _sdlc(args.project),
                                   debt_epic=args.epic, repos=_csv(args.repos))
        if args.pmcmd == "to-brain":
            return store.to_brain(args.id)

    s = _sdlc(args.project)

    if args.cmd == "create-epic":
        s.create_epic(args.epic, args.title); return {"epic": args.epic, "created": True}
    if args.cmd == "create-ticket":
        t = s.create_ticket(args.epic, args.story, args.title, _csv(args.deps), _csv(args.repos))
        return dataclasses.asdict(t)
    if args.cmd == "get":
        return s.get_ticket(args.story)
    if args.cmd == "list":
        return {"tickets": [dataclasses.asdict(t) for t in s.list_backlog(args.status)]}
    if args.cmd == "next":
        return {"epic": args.epic, "next": s.next(args.epic)}
    if args.cmd == "set-status":
        return dataclasses.asdict(s.set_status(args.story, args.status))
    if args.cmd == "link":
        return dataclasses.asdict(s.link_artifact(args.story, args.kind, args.path))
    if args.cmd == "reject":
        return s.reject(args.story, args.to, args.note, actor=args.by)
    if args.cmd in _GATE_CMDS:
        from .gates import run_gate
        signers = (load_config(resolve_workspace(args.project)).get("gates") or {}).get("signers")
        return run_gate(s, _GATE_CMDS[args.cmd], args.target, args.verdict, review=args.review, signers=signers)
    if args.cmd == "deploy-target":
        return resolve_deploy_target(load_config(resolve_workspace(args.project)), args.repo, args.env)
    if args.cmd == "journal":
        return s.journal(args.story, args.entry, actor=args.by)
    if args.cmd == "workspace":
        from .agentws import build_agent_workspace
        return build_agent_workspace(args.project, args.story, branch=args.branch, agent=args.agent)
    if args.cmd == "worktree-clean":
        from .agentws import clean_workspace
        return clean_workspace(args.project, args.story, branch=args.branch, ref=args.ref)
    if args.cmd == "worktree":
        from . import worktree as wt
        t = s.get_ticket(args.story)
        branch = args.branch or t.get("branch")
        if not branch:
            raise ValueError(f"aucune branche pour {args.story} (ticket.branch vide, passe --branch)")
        man = resolved_manifest(args.project)
        ref = man.get("refBranch") or "main"
        names = ([args.repo] if args.repo else t.get("repos")) or []
        out: dict[str, dict] = {}
        for name in names:
            p = man["repos"].get(name)
            if not p:
                out[name] = {"error": "repo non résolu dans le manifest (reposRoot/repos ?)"}
                continue
            # A story ALWAYS starts from the project's reference branch, fetched. Falling back to the
            # repo's current HEAD used to base stories on whatever branch happened to be checked out.
            base = args.base or wt.fetch_base(p, ref)
            res = wt.ensure_worktree(p, branch, base=base)
            res["base"] = base
            # Surfaced, never silently corrected: an existing branch is reused as-is, so a branch cut
            # from a stale base stays stale — the caller has to see it.
            res["basedOnRef"] = wt.is_based_on(p, branch, base)
            out[name] = res
        return {"story": args.story, "branch": branch, "refBranch": ref, "worktrees": out}
    raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    from .brain import BrainError
    from .brain.cli import CommandResult
    try:
        res = run(argv)
        if isinstance(res, bytes):          # `doc read`: raw document bytes, nothing added
            sys.stdout.flush()
            sys.stdout.buffer.write(res)
            sys.stdout.buffer.flush()
            return 0
        if isinstance(res, CommandResult):
            print(res.text if res.text is not None else json.dumps(res.payload, indent=2, ensure_ascii=False))
            return res.exit_code
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    except BrainError as e:  # brain library error: stable code, exit 2
        print(json.dumps({"error": e.message, "code": e.code}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — CLI: message propre
        err = {"error": str(e)}
        if getattr(e, "code", None) and isinstance(e.code, str):  # stable code of a refused gate
            err["code"] = e.code
        if getattr(e, "diagnostic", None):  # e.g. the redacted stderr of a failed git call
            err["diagnostic"] = e.diagnostic
        print(json.dumps(err, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
