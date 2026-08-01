"""Résolution du workspace SDLC + lecture/résolution de `sdlc.config.json` (le **manifest**).

Ordre de résolution du workspace : env `SDLC_WORKSPACE` → registre `~/.claude/sdlc/projects.json`
(par préfixe) → remontée de l'arbo à la recherche d'un `sdlc.config.json`.

Le **manifest** est la carte du projet (couche 1 de la pile d'autonomie) : d'où on lit `repos`,
`roles`, `brain`, `refBranch`, `deploy`. `resolved_manifest()` en donne une vue **résolue** (chemins
absolus) — c'est ce que la commande `sdlc config` expose aux agents (au lieu de reverse-engineerer).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_ESCALATION = {
    "review": "auto", "deploy": "human-confirm",
    "recette": "auto-then-human", "nonreg": "human-on-fail",
}


def registry_path() -> Path:
    return Path.home() / ".claude" / "sdlc" / "projects.json"


def resolve_workspace(project: str | None = None, start: str | Path | None = None) -> Path:
    env = os.environ.get("SDLC_WORKSPACE")
    if env:
        return Path(env)

    if project:
        reg = registry_path()
        if reg.exists():
            data = json.loads(reg.read_text())
            p = data.get("projects", {}).get(project, {}).get("workspace")
            if p:
                return Path(p)

    cur = Path(start or Path.cwd()).resolve()
    # remontée de l'arbo (cas : on est DANS le repo data)
    for d in [cur, *cur.parents]:
        if (d / "sdlc.config.json").exists():
            return d
        if (d / "sample-proj-sdlc-local" / "sdlc.config.json").exists():
            return d / "sample-proj-sdlc-local"
    # déduction par le CWD (cas : on est dans un repo de CODE) — matche le CWD contre le
    # reposRoot / les repos de chaque projet enregistré. Aucune hypothèse sur le naming.
    inferred = infer_project_workspace(cur)
    if inferred:
        return Path(inferred)
    raise FileNotFoundError(
        "workspace SDLC introuvable (env SDLC_WORKSPACE, --project, sdlc.config.json en remontant "
        "l'arbo, ou CWD sous le reposRoot/les repos d'un projet enregistré)"
    )


def _registered_projects() -> dict:
    reg = registry_path()
    return json.loads(reg.read_text()).get("projects", {}) if reg.exists() else {}


def current_project(start: str | Path | None = None) -> str | None:
    """Préfixe du projet **courant** déduit du CWD (ou `start`) : le projet enregistré dont le
    workspace data / reposRoot / un repo contient le CWD. `None` si aucun ne matche (CWD hors projet).
    C'est ce qui lève l'ambiguïté de `sdlc projects` quand plusieurs projets sont enregistrés.
    """
    try:
        ws = infer_project_workspace(start or Path.cwd())
    except OSError:
        return None
    if not ws:
        return None
    ws_res = str(Path(ws).resolve())
    for prefix, meta in _registered_projects().items():
        w = meta.get("workspace")
        if w and str(Path(w).resolve()) == ws_res:
            return prefix
    return None


def infer_project_workspace(start: str | Path) -> str | None:
    """Déduit le workspace data à partir du CWD : le projet dont le `reposRoot`, un repo, ou le repo
    data **contient** le CWD. Match le plus **spécifique** (chemin le plus long) en cas de chevauchement.
    """
    try:
        start = Path(start).resolve()
    except OSError:
        return None
    best: tuple[int, str] | None = None
    for _prefix, meta in _registered_projects().items():
        ws = meta.get("workspace")
        if not ws:
            continue
        cfg = load_config(ws)
        candidates = [str(Path(ws).resolve())]                 # le repo data lui-même
        if cfg.get("reposRoot"):
            candidates.append(_expand(cfg["reposRoot"]))       # la racine des repos de code
        candidates += [p for p in resolve_repos(cfg).values() if p]  # chaque repo résolu
        for cand in candidates:
            try:
                cp = Path(cand).resolve()
            except OSError:
                continue
            if start == cp or start.is_relative_to(cp):
                score = len(str(cp))
                if best is None or score > best[0]:
                    best = (score, str(ws))
    return best[1] if best else None


def load_config(workspace: str | Path) -> dict:
    """Lit le manifest brut + pose les defaults (backward-compatible)."""
    p = Path(workspace) / "sdlc.config.json"
    cfg = json.loads(p.read_text()) if p.exists() else {}
    cfg.setdefault("escalation", dict(DEFAULT_ESCALATION))
    cfg.setdefault("board", {"type": "null"})
    cfg.setdefault("repos", {})
    cfg.setdefault("reposRoot", None)
    cfg.setdefault("roles", {})
    cfg.setdefault("refBranch", "main")
    cfg.setdefault("deploy", {})
    cfg.setdefault("recette", {})
    # type/stack technique par repo : { "<repo>": "java-spring" | "java" | "node" | "python" | ... }.
    #   Explicite côté projet ; à défaut, le CLI l'auto-détecte (pom+spring-boot -> java-spring, package.json
    #   -> node, pyproject/requirements -> python, …). C'est LE critère de matching des skills.
    cfg.setdefault("stacks", {})
    # guidelines de code par STACK (la politique, générique) : { "java-spring": ["rest-api-design", ...] }.
    #   Le CLI résout repo -> stack -> skills et surface `skillsByRepo`. Un repo dont la stack n'a aucune
    #   entrée (ex. python) n'hérite d'aucun skill.
    cfg.setdefault("guidelines", {})
    # identité : source des credentials utilisée par les agents.
    #   "host" = creds ambiantes de l'opérateur (curl -s -n via ~/.netrc, ~/.kube/config, gh/glab
    #   keyring) — jamais lues ni affichées. Futur : "service" = creds scopées injectées dans la bulle.
    cfg.setdefault("credentials", {"source": "host"})
    # permissions par agent-rôle (allow/deny) injectées dans la bulle par `sdlc workspace --agent`.
    #   { "deny": [...partagé...], "agents": { "deployer": {"allow": [...]}, "reviewer": {...} } }
    cfg.setdefault("permissions", {})
    return cfg


# --- résolution de chemins (reposRoot / absolu / relatif au workspace) ---

def _expand(p: str | Path) -> str:
    return str(Path(p).expanduser())


def _join(root: str | None, value: str) -> str | None:
    if os.path.isabs(value):
        return _expand(value)
    if root:
        return _expand(Path(root) / value)
    return None  # non résoluble sans reposRoot ni chemin absolu


def resolve_repos(cfg: dict) -> dict[str, str | None]:
    """`repos` (liste de noms **ou** map name→path) → map name→chemin absolu (None si non résoluble).

    - liste `["back-tenant", ...]` → chaque nom résolu via `reposRoot`.
    - map `{"back-tenant": "/abs"}` → chemin tel quel (absolu) ou joint à `reposRoot` (relatif),
      `null` → résolu via `reposRoot/<nom>`.
    """
    root = cfg.get("reposRoot")
    repos = cfg.get("repos", {})
    out: dict[str, str | None] = {}
    if isinstance(repos, list):
        for name in repos:
            out[name] = _join(root, name)
    else:
        for name, val in repos.items():
            out[name] = _join(root, name) if val in (None, "") else _join(root, str(val))
    return out


def resolve_path(value: str | None, cfg: dict, workspace: str | Path) -> str | None:
    """Résout `brain`/chemin arbitraire : absolu tel quel, sinon relatif à `reposRoot`, sinon au workspace."""
    if not value:
        return None
    if os.path.isabs(value):
        return _expand(value)
    root = cfg.get("reposRoot")
    if root:
        return _expand(Path(root) / value)
    return _expand(Path(workspace) / value)


def detect_stack(repo_path: str | Path | None) -> str | None:
    """Devine le type/stack d'un repo à partir de ses fichiers-marqueurs. Critère de matching des skills.
    pom.xml + spring-boot -> "java-spring" ; pom/gradle Java sinon -> "java" ; package.json -> "node" ;
    pyproject/requirements/setup.py -> "python". Renvoie None si indéterminé (aucun skill hérité)."""
    if not repo_path:
        return None
    p = Path(repo_path)
    if not p.exists():
        return None
    pom = p / "pom.xml"
    if pom.exists():
        try:
            txt = pom.read_text(errors="ignore")
        except OSError:
            txt = ""
        return "java-spring" if "spring-boot" in txt else "java"
    if (p / "build.gradle").exists() or (p / "build.gradle.kts").exists():
        gr = ""
        for g in ("build.gradle", "build.gradle.kts"):
            try:
                gr += (p / g).read_text(errors="ignore") if (p / g).exists() else ""
            except OSError:
                pass
        return "java-spring" if "spring-boot" in gr else "java"
    if (p / "package.json").exists():
        return "node"
    if (p / "pyproject.toml").exists() or (p / "requirements.txt").exists() or (p / "setup.py").exists():
        return "python"
    return None


def resolve_stacks(cfg: dict, repos: dict) -> dict:
    """repo -> stack : override explicite `stacks` du manifest, sinon auto-détection."""
    explicit = cfg.get("stacks", {})
    out: dict = {}
    for name, path in repos.items():
        out[name] = explicit.get(name) or detect_stack(path)
    return out


def resolved_manifest(project: str | None = None, workspace: str | Path | None = None) -> dict:
    """Vue **résolue** du manifest (chemins absolus) — la sortie de `sdlc config`, lue par les agents."""
    ws = Path(workspace) if workspace else resolve_workspace(project)
    cfg = load_config(ws)
    repos = resolve_repos(cfg)
    # matching des skills : repo -> stack (explicite ou détecté) -> skills (politique par stack).
    stacks = resolve_stacks(cfg, repos)
    guidelines = cfg.get("guidelines", {})  # stack -> [skills]
    skills_by_repo = {
        name: list(guidelines.get(st, [])) for name, st in stacks.items() if st and guidelines.get(st)
    }
    return {
        "prefix": cfg.get("prefix"),
        "workspace": str(ws),
        "reposRoot": _expand(cfg["reposRoot"]) if cfg.get("reposRoot") else None,
        "repos": repos,
        "roles": cfg.get("roles", {}),
        "stacks": stacks,
        "brain": resolve_path(cfg.get("brain"), cfg, ws),
        "refBranch": cfg.get("refBranch", "main"),
        "deploy": cfg.get("deploy", {}),
        "recette": cfg.get("recette", {}),
        "guidelines": guidelines,
        "skillsByRepo": skills_by_repo,
        "credentials": cfg.get("credentials", {"source": "host"}),
        "permissions": cfg.get("permissions", {}),
        "escalation": cfg["escalation"],
        "board": cfg["board"],
        "schemaVersion": cfg.get("schemaVersion", "0.1.0"),
    }
