"""Spec and feature gates: the agent recommends, a human decides (PRD AISDLC-POASSIST D7-D14).

A gate is recorded by `sdlc validate-spec-func | validate-spec-tech | validate-feature <target> --verdict <path>`.
The command never validates anything by itself: it checks that the verdict written by `/process-review` exists
and was **signed by a human**, then records the decision (journal, links, debt items) and moves the stories.

Documents (paths relative to the data repository):
- review (agent, advisory): `review-spec-func.md`, `review-spec-tech.md`, `review-feature.md` — numbered findings
  `B<n>` blocking, `M<n>` major, `m<n>` minor, `S<n>` suggestion; ids are never reused across versions.
- verdict (human): `review-<gate>-verdict.md` (feature: one per role, `review-feature-verdict-<role>.md`) whose
  front matter carries `gate`, `target`, `review`, `review_version`, `status: draft|signed`, `outcome`, `signed_by`,
  `signed_at` (+ `role` for the feature gate) and whose `## Décisions` table references the findings by id.

Every check runs before the first write: a refused gate leaves the workspace untouched.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .post_mortem import PostMortemStore
from .status import PIPELINE, Status


class GateRefused(ValueError):
    """The gate cannot be recorded; nothing was written."""


@dataclass(frozen=True)
class Gate:
    name: str
    command: str
    source: str
    dest: str
    review_file: str
    review_kind: str
    verdict_kind: str
    roles: tuple[str, ...] = ()

    def verdict_kind_for(self, role: str | None) -> str:
        return f"{self.verdict_kind}_{role}" if role else self.verdict_kind


GATES: dict[str, Gate] = {
    "spec_func": Gate("spec_func", "validate-spec-func", Status.SPEC_FUNC.value, Status.SPEC_FUNC_VALIDATED.value,
                      "review-spec-func.md", "review_spec_func", "review_spec_func_verdict"),
    "spec_tech": Gate("spec_tech", "validate-spec-tech", Status.SPEC_TECH.value, Status.SPEC_VALIDATED.value,
                      "review-spec-tech.md", "review_spec_tech", "review_spec_tech_verdict"),
    "feature": Gate("feature", "validate-feature", Status.SPEC_VALIDATED.value, Status.FEATURE_VALIDATED.value,
                    "review-feature.md", "review_feature", "review_feature_verdict", roles=("po", "techlead")),
}

OUTCOMES = ("validated", "validated_with_reserves", "returned", "bypassed")
ADVANCING = frozenset({"validated", "validated_with_reserves", "bypassed"})
# The worse of two advancing outcomes wins when the two feature verdicts are combined.
_OUTCOME_RANK = {"validated": 0, "validated_with_reserves": 1, "bypassed": 2, "returned": 3}
FINAL_DECISIONS = frozenset({"applied", "other", "reserve", "rejected", "bypassed"})
DEBT_DECISIONS = frozenset({"reserve", "bypassed"})
NEEDS_REASON = frozenset({"rejected", "bypassed"})
_DECISION_ALIASES = {
    "appliquer": "applied", "appliqué": "applied", "applique": "applied", "apply": "applied",
    "autre": "other", "autre correction": "other",
    "réserve": "reserve", "reserve": "reserve", "reserved": "reserve",
    "rejeter": "rejected", "rejeté": "rejected", "rejete": "rejected", "reject": "rejected",
    "passer outre": "bypassed", "bypass": "bypassed",
    "discuter": "discuss", "discussion": "discuss",
}
_SEVERITY_BY_LETTER = {"B": "high", "M": "medium", "m": "low", "S": "low", "H": "medium"}
ENGINE_AGENTS = frozenset({"harry-archi", "reviewer", "deployer", "recetteur", "fixer", "demo", "e2e-author",
                           "nonreg-runner", "investigator"})
_AGENT_IDENTITIES = ENGINE_AGENTS | {"harry", "claude", "agent", "ai", "bot", "auto", "system", "orchestrator"}

_FINDING_ROW = re.compile(r"^\|\s*([BMmS]\d+)\s*\|", re.M)
_DECISION_ROW = re.compile(r"^\|\s*([BMmS]\d+|H\d+)\s*\|([^|\n]*)\|([^|\n]*)\|?")
_DECISIONS_HEADING = re.compile(r"^##\s+D[ée]cisions?\b", re.I)


# --- parsing -------------------------------------------------------------------------------------------------

def front_matter(text: str) -> dict[str, str]:
    """`key: value` lines of a leading `---` block (no full YAML: the engine has no dependency)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return {}  # unterminated block: not a front matter


def review_findings(text: str) -> dict[str, str]:
    """Finding ids of a review (every version) -> severity letter."""
    return {m.group(1): m.group(1)[0] for m in _FINDING_ROW.finditer(text)}


def _decisions_section(text: str) -> str:
    out, grab = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            grab = bool(_DECISIONS_HEADING.match(line))
            continue
        if grab:
            out.append(line)
    return "\n".join(out)


def _clean(cell: str) -> str:
    return cell.strip().strip("`*_ ").strip()


def normalize_decision(raw: str) -> str:
    d = _clean(raw).lower()
    return _DECISION_ALIASES.get(d, d)


def verdict_decisions(text: str) -> dict[str, tuple[str, str]]:
    """Rows of the `## Décisions` table: id -> (normalized decision, reason)."""
    out: dict[str, tuple[str, str]] = {}
    for line in _decisions_section(text).splitlines():
        m = _DECISION_ROW.match(line.strip())
        if m:
            out[m.group(1)] = (normalize_decision(m.group(2)), _clean(m.group(3)))
    return out


def blob_ref(path: Path) -> str:
    """First 12 hex chars of `git hash-object <path>`, computed without git."""
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()[:12]


def is_agent_identity(name: str | None) -> bool:
    n = (name or "").strip().lower()
    return not n or n in _AGENT_IDENTITIES or "claude" in n


def severity_of(finding_id: str) -> str:
    return _SEVERITY_BY_LETTER.get(finding_id[:1], "medium")


# --- verdict check -------------------------------------------------------------------------------------------

@dataclass
class Verdict:
    path: str
    ref: str
    review: str
    review_ref: str
    outcome: str
    signed_by: str
    signed_at: str
    role: str | None
    decisions: dict[str, tuple[str, str]] = field(default_factory=dict)


def _rel(root: Path, p: str | Path) -> tuple[str, Path]:
    path = Path(p)
    absolute = path if path.is_absolute() else root / path
    try:
        return str(absolute.resolve().relative_to(root.resolve())), absolute
    except ValueError:
        return str(absolute), absolute


def check_verdict(root: str | Path, path: str, gate: str, target: str, review: str | None = None) -> Verdict:
    """Return the verdict when it can carry the gate, raise `GateRefused` naming the cause otherwise."""
    root = Path(root)
    g = GATES[gate]
    rel, vpath = _rel(root, path)
    if not vpath.is_file():
        raise GateRefused(f"verdict not found: {rel}")
    text = vpath.read_text(encoding="utf-8")
    fm = front_matter(text)
    if fm.get("kind", "verdict") != "verdict":
        raise GateRefused(f"{rel}: kind is '{fm.get('kind')}', expected 'verdict'")
    if fm.get("gate") != gate:
        raise GateRefused(f"{rel}: gate is '{fm.get('gate', '')}', expected '{gate}' ({g.command})")
    if fm.get("target") != target:
        raise GateRefused(f"{rel}: target is '{fm.get('target', '')}', expected '{target}'")
    status = fm.get("status", "")
    if status != "signed":
        raise GateRefused(f"{rel}: verdict not signed (status: {status or 'missing'}) — a draft cannot carry the "
                          f"gate; the human signs it in /process-review")
    outcome = fm.get("outcome", "")
    if outcome not in OUTCOMES:
        raise GateRefused(f"{rel}: outcome '{outcome}' invalid, expected one of {', '.join(OUTCOMES)}")
    signed_by = fm.get("signed_by", "").strip()
    if is_agent_identity(signed_by):
        raise GateRefused(f"{rel}: the verdict must be signed by a human (signed_by: '{signed_by}'); "
                          f"an agent never signs a gate")
    if not fm.get("signed_at", "").strip():
        raise GateRefused(f"{rel}: signed_at missing")
    role = fm.get("role") or None
    if g.roles and role not in g.roles:
        raise GateRefused(f"{rel}: role '{role or ''}' invalid for the {gate} gate, expected one of "
                          f"{', '.join(g.roles)}")
    declared = fm.get("review", "").strip()
    if review and declared and _rel(root, review)[0] != _rel(root, declared)[0]:
        raise GateRefused(f"{rel}: review mismatch — --review {review} but the verdict references {declared}")
    chosen = review or declared
    if not chosen:
        raise GateRefused(f"{rel}: no review referenced (front matter 'review' or --review)")
    rrel, rpath = _rel(root, chosen)
    if not rpath.is_file():
        raise GateRefused(f"review not found: {rrel}")
    rtext = rpath.read_text(encoding="utf-8")
    rfm = front_matter(rtext)
    if rfm.get("gate") and rfm["gate"] != gate:
        raise GateRefused(f"{rrel}: review gate is '{rfm['gate']}', expected '{gate}'")
    if rfm.get("version") and fm.get("review_version") and rfm["version"] != fm["review_version"]:
        raise GateRefused(f"{rel}: signed on review version {fm['review_version']} but {rrel} is at version "
                          f"{rfm['version']} — process the targeted re-review first")
    findings = review_findings(rtext)
    decisions = verdict_decisions(text)
    missing = [f for f in findings if f not in decisions]
    if missing:
        raise GateRefused(f"{rel}: findings without a decision: {', '.join(missing)}")
    unknown = [i for i in decisions if not i.startswith("H") and i not in findings]
    if unknown:
        raise GateRefused(f"{rel}: decisions on unknown findings: {', '.join(unknown)}")
    pending = [i for i, (d, _) in decisions.items() if d not in FINAL_DECISIONS]
    if pending:
        raise GateRefused(f"{rel}: undecided findings (discuss or unknown decision): {', '.join(pending)}")
    unexplained = [i for i, (d, why) in decisions.items() if d in NEEDS_REASON and not why]
    if unexplained:
        raise GateRefused(f"{rel}: rejected/bypassed without a reason: {', '.join(unexplained)}")
    return Verdict(path=rel, ref=blob_ref(vpath), review=rrel, review_ref=blob_ref(rpath), outcome=outcome,
                   signed_by=signed_by, signed_at=fm["signed_at"].strip(), role=role, decisions=decisions)


# --- gate run ------------------------------------------------------------------------------------------------

def _index(status: str) -> int:
    try:
        return PIPELINE.index(Status(status))
    except ValueError:
        return -1


def _targets(sdlc, g: Gate, target: str) -> list:
    tickets = sdlc.list_backlog(None)
    by_id = {t.id: t for t in tickets}
    if g.name == "feature":
        if target in by_id:
            raise GateRefused(f"{g.command}: the feature gate targets an epic, '{target}' is a story")
        members = [t for t in tickets if t.epic == target and not t.supersededBy]
        if not members:
            raise GateRefused(f"{g.command}: unknown epic '{target}'")
        floor = _index(g.source)
        lagging = [f"{t.id} ({t.status})" for t in members if _index(t.status) < floor]
        if lagging:
            raise GateRefused(f"{g.command}: every story of {target} must be {g.source} first — "
                              f"not yet: {', '.join(lagging)}")
        found = [t for t in members if t.status == g.source]
        if not found:
            raise GateRefused(f"{g.command}: no story of {target} in {g.source}")
        return found
    if target in by_id:
        t = by_id[target]
        if t.status != g.source:
            raise GateRefused(f"{g.command}: {target} is {t.status}, expected {g.source}")
        return [t]
    found = [t for t in tickets if t.epic == target and t.status == g.source]
    if not found:
        raise GateRefused(f"{g.command}: '{target}' is neither a story nor an epic with stories in {g.source}")
    return found


def _now(now: str | None) -> str:
    return now or datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_gate(sdlc, gate: str, target: str, verdicts: list[str] | None, review: str | None = None,
             now: str | None = None) -> dict:
    g = GATES[gate]
    root = Path(sdlc.ws.root)
    if not verdicts:
        raise GateRefused(f"{g.command}: --verdict <path> is required — the gate rests on a verdict signed by a "
                          f"human (review by harry-archi, then /process-review)")
    targets = _targets(sdlc, g, target)
    checked = [check_verdict(root, v, gate, target, review) for v in verdicts]

    # --- decide (still read-only) ---
    by_role: dict[str | None, Verdict] = {}
    for v in checked:
        if v.role in by_role:
            raise GateRefused(f"{g.command}: two verdicts for the same role '{v.role}'" if v.role
                              else f"{g.command}: one verdict per spec gate")
        by_role[v.role] = v
    earlier: dict[str, Verdict] = {}
    for role in g.roles:
        if role in by_role:
            continue
        linked = targets[0].artifacts.get(g.verdict_kind_for(role))
        if linked:
            try:
                earlier[role] = check_verdict(root, linked, gate, target)
            except GateRefused:
                pass  # a previously linked verdict that no longer holds counts as missing
    present = {**by_role, **earlier}
    waiting = [r for r in g.roles if r not in present]
    outcome = max((v.outcome for v in present.values()), key=_OUTCOME_RANK.__getitem__)
    advance = not waiting and outcome in ADVANCING

    # --- write: debt, then links + journal + transition per story ---
    store = PostMortemStore(root)
    story = target if len(targets) == 1 and targets[0].id == target else None
    epic = targets[0].epic
    debt: list[str] = []
    for v in checked:
        for fid, (decision, why) in v.decisions.items():
            if decision not in DEBT_DECISIONS:
                continue
            tag = f"[{gate} {target} {fid}]"
            known = next((i for i in store.list(kind="debt") if i.text.startswith(tag)), None)
            if known is not None:
                if known.id not in debt:
                    debt.append(known.id)
                continue
            item = store.add(agent="human", kind="debt", severity=severity_of(fid), epic=epic, story=story,
                             text=f"{tag} {decision}: {why or 'no reason given'} (verdict {v.path}, signed by "
                                  f"{v.signed_by})")
            debt.append(item.id)

    stamp = _now(now)
    signers = ", ".join(f"{v.signed_by}" + (f" ({v.role})" if v.role else "") for v in present.values())
    if advance:
        head = f"GATE {gate}  {g.source} -> {g.dest}  ({outcome}, signé par: {signers})"
    elif waiting:
        head = (f"GATE {gate}  verdict {', '.join(r for r in by_role if r)} enregistré ({outcome}, signé par: "
                f"{signers}) — attend: {', '.join(waiting)}")
    else:
        head = f"GATE {gate}  {outcome} (signé par: {signers}) — pas de transition, retour en correction"
    lines = [f"## {stamp} — {head}"]
    for review_path, review_ref in dict.fromkeys((v.review, v.review_ref) for v in present.values()):
        lines.append(f"review: {review_path}@{review_ref}")
    for v in present.values():
        role = f" {v.role}" if v.role else ""
        lines.append(f"verdict{role}: {v.path}@{v.ref} (signed {v.signed_at}, {v.signed_by}, {v.outcome})")
    if debt:
        lines.append(f"debt: {', '.join(debt)}")
    entry = "\n".join(lines)

    advanced: list[str] = []
    for t in targets:
        sdlc.link_artifact(t.id, g.review_kind, checked[0].review)
        for v in checked:
            sdlc.link_artifact(t.id, g.verdict_kind_for(v.role), v.path)
        sdlc.ws.journal_add(t.id, entry)
        if advance:
            advanced.append(sdlc.set_status(t.id, g.dest).id)
    return {
        "gate": gate, "command": g.command, "target": target, "outcome": outcome,
        "signedBy": [v.signed_by for v in present.values()],
        "advanced": advanced, "recorded": [t.id for t in targets], "waiting": waiting,
        "review": checked[0].review,
        "verdicts": {(v.role or gate): f"{v.path}@{v.ref}" for v in present.values()},
        "debt": debt,
    }
