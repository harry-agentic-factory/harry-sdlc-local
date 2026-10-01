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
    """The gate cannot be recorded; nothing was written. `code` is stable, the message is for humans."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


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
_INLINE_COMMENT = re.compile(r"\s+#")
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
        if value[:1] in ("\"", "'") and value.find(value[0], 1) > 0:
            value = value[1:value.find(value[0], 1)]  # quoted: anything after the closing quote is ignored
        else:
            # YAML inline comment (`status: signed  # ...`, as in the /process-review template)
            value = _INLINE_COMMENT.split(value, 1)[0].strip() if not value.startswith("#") else ""
        out[key.strip()] = value
    return {}  # unterminated block: not a front matter


def review_findings(text: str) -> dict[str, str]:
    """Finding ids of a review (every version) -> severity letter."""
    return {m.group(1): m.group(1)[0] for m in _FINDING_ROW.finditer(text)}


# --- finding roles (AISDLC-POASSIST-14, PRD D27) ----------------------------------------------------------------
# At the feature gate the agent review assigns each finding to a role in a `Rôle` column; each role verdict
# decides only the findings assigned to it. A review without that column (or a finding without a readable
# role) keeps the historical rule: both roles decide it.

GATE_ROLES = ("po", "techlead")
ROLE_HEADERS = frozenset({"rôle", "role", "rôles", "roles", "owner", "owners", "pour", "porteur"})
_ROLE_TOKENS = {
    "po": ("po",), "product owner": ("po",), "productowner": ("po",),
    "techlead": ("techlead",), "tech lead": ("techlead",), "tech-lead": ("techlead",),
    "tech_lead": ("techlead",), "tl": ("techlead",),
    "both": GATE_ROLES, "les deux": GATE_ROLES, "deux": GATE_ROLES, "tous": GATE_ROLES, "all": GATE_ROLES,
}
_ROLE_SPLIT = re.compile(r"\s*(?:\+|,|/|&|;|\bet\b|\band\b)\s*", re.I)
_HEADER_ROW = re.compile(r"^\|\s*#\s*\|")
_TARGETED = re.compile(r"^##\s+revue\s+cibl[ée]e", re.I)


def _row_cells(line: str) -> list[str]:
    raw = line.strip()
    raw = raw[1:] if raw.startswith("|") else raw
    raw = raw[:-1] if raw.endswith("|") else raw
    return [c.strip() for c in raw.split("|")]


def _header_name(cell: str) -> str:
    return cell.strip().strip("`*_ ").strip().lower()


def parse_roles(cell: str) -> tuple[str, ...]:
    """`[po]`, `techlead`, `tech lead`, `TL`, `po+techlead`, `les deux`, `both` … -> roles; unreadable/empty ->
    both roles (never a finding nobody decides)."""
    raw = cell.strip().strip("`*_[]() ").strip().lower()
    if raw in _ROLE_TOKENS:
        return _ROLE_TOKENS[raw]
    roles: set[str] = set()
    for token in _ROLE_SPLIT.split(raw):
        token = token.strip("`*_[]() ").strip()
        if not token:
            continue
        if token not in _ROLE_TOKENS:
            return GATE_ROLES
        roles.update(_ROLE_TOKENS[token])
    return tuple(r for r in GATE_ROLES if r in roles) or GATE_ROLES


def review_roles(text: str) -> dict[str, tuple[str, ...]]:
    """Finding id -> roles that decide it, read from the `Rôle` column BY HEADER NAME.

    Precedence (same as the platform's `parse_review`): the rows of a `## Revue ciblée` section first, then the
    document order; the first occurrence of an id wins. A finding in a table without a role column -> both."""
    targeted: list[tuple[str, tuple[str, ...]]] = []
    others: list[tuple[str, tuple[str, ...]]] = []
    role_col: int | None = None
    in_targeted = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_targeted = bool(_TARGETED.match(stripped))
            continue
        if _HEADER_ROW.match(stripped):
            names = [_header_name(c) for c in _row_cells(stripped)]
            role_col = next((i for i, n in enumerate(names) if n in ROLE_HEADERS), None)
            continue
        m = _FINDING_ROW.match(stripped)
        if not m:
            continue
        cells = _row_cells(stripped)
        roles = parse_roles(cells[role_col]) if role_col is not None and role_col < len(cells) else GATE_ROLES
        (targeted if in_targeted else others).append((m.group(1), roles))
    out: dict[str, tuple[str, ...]] = {}
    for fid, roles in [*targeted, *others]:
        out.setdefault(fid, roles)
    return out


def findings_for_role(text: str, role: str | None) -> dict[str, str]:
    """The review findings a verdict of `role` must decide (all of them without a role)."""
    findings = review_findings(text)
    if not role:
        return findings
    roles = review_roles(text)
    return {f: s for f, s in findings.items() if role in roles.get(f, GATE_ROLES)}


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


_DECISION_HEADERS = {"décision": "decision", "decision": "decision", "motif": "reason", "raison": "reason",
                     "reason": "reason", "justification": "reason"}


def verdict_decisions(text: str) -> dict[str, tuple[str, str]]:
    """Rows of the `## Décisions` table: id -> (normalized decision, reason).

    Columns are read BY HEADER NAME when the table has a `| # | … |` header naming them (`Décision`, `Motif`);
    otherwise by position (`| # | Décision | Motif | …`), the canonical layout."""
    out: dict[str, tuple[str, str]] = {}
    decision_col, reason_col = 1, 2
    for line in _decisions_section(text).splitlines():
        stripped = line.strip()
        if _HEADER_ROW.match(stripped):
            names = [_DECISION_HEADERS.get(_header_name(c), "") for c in _row_cells(stripped)]
            if "decision" in names:
                decision_col = names.index("decision")
                reason_col = names.index("reason") if "reason" in names else -1
            continue
        m = _DECISION_ROW.match(stripped)
        if not m:
            continue
        cells = _row_cells(stripped)
        decision = cells[decision_col] if decision_col < len(cells) else ""
        reason = cells[reason_col] if 0 <= reason_col < len(cells) else ""
        out[m.group(1)] = (normalize_decision(decision), _clean(reason))
    return out


def blob_ref(path: Path) -> str:
    """First 12 hex chars of `git hash-object <path>`, computed without git."""
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()[:12]


def is_agent_identity(name: str | None) -> bool:
    """Guard against an accidental self-signature, not against impersonation (the prompts forbid signing)."""
    n = (name or "").strip().lower()
    return not n or n in _AGENT_IDENTITIES or n.startswith("claude-")


def severity_of(finding_id: str) -> str:
    return _SEVERITY_BY_LETTER.get(finding_id[:1], "medium")


# --- verdict check -------------------------------------------------------------------------------------------

@dataclass
class Verdict:
    path: str
    ref: str
    review: str
    review_ref: str
    review_version: str
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


def check_verdict(root: str | Path, path: str, gate: str, target: str, review: str | None = None,
                  signers: list[str] | None = None) -> Verdict:
    """Return the verdict when it can carry the gate, raise `GateRefused` naming the cause otherwise.

    `signers`: optional allow-list (`gates.signers` of the project manifest); when set, `signed_by` must be in it.
    """
    root = Path(root)
    g = GATES[gate]
    rel, vpath = _rel(root, path)
    if not vpath.is_file():
        raise GateRefused(f"verdict not found: {rel}", "verdict_not_found")
    text = vpath.read_text(encoding="utf-8")
    fm = front_matter(text)
    if fm.get("kind", "verdict") != "verdict":
        raise GateRefused(f"{rel}: kind is '{fm.get('kind')}', expected 'verdict'", "wrong_gate")
    if fm.get("gate") != gate:
        raise GateRefused(f"{rel}: gate is '{fm.get('gate', '')}', expected '{gate}' ({g.command})", "wrong_gate")
    if fm.get("target") != target:
        raise GateRefused(f"{rel}: target is '{fm.get('target', '')}', expected '{target}'", "wrong_target")
    status = fm.get("status", "")
    if status != "signed":
        raise GateRefused(f"{rel}: verdict not signed (status: {status or 'missing'}) — a draft cannot carry the "
                          f"gate; the human signs it in /process-review", "not_signed")
    outcome = fm.get("outcome", "")
    if outcome not in OUTCOMES:
        raise GateRefused(f"{rel}: outcome '{outcome}' invalid, expected one of {', '.join(OUTCOMES)}",
                          "bad_outcome")
    signed_by = fm.get("signed_by", "").strip()
    if is_agent_identity(signed_by):
        raise GateRefused(f"{rel}: the verdict must be signed by a human (signed_by: '{signed_by}'); "
                          f"an agent never signs a gate", "agent_signer")
    if signers and signed_by.lower() not in {s.strip().lower() for s in signers}:
        raise GateRefused(f"{rel}: '{signed_by}' is not in the signers allowed by the project (gates.signers)",
                          "signer_not_allowed")
    if not fm.get("signed_at", "").strip():
        raise GateRefused(f"{rel}: signed_at missing", "not_signed")
    role = fm.get("role") or None
    if g.roles and role not in g.roles:
        raise GateRefused(f"{rel}: role '{role or ''}' invalid for the {gate} gate, expected one of "
                          f"{', '.join(g.roles)}", "bad_role")
    declared = fm.get("review", "").strip()
    if review and declared and _rel(root, review)[0] != _rel(root, declared)[0]:
        raise GateRefused(f"{rel}: review mismatch — --review {review} but the verdict references {declared}",
                          "review_missing")
    chosen = review or declared
    if not chosen:
        raise GateRefused(f"{rel}: no review referenced (front matter 'review' or --review)", "review_missing")
    rrel, rpath = _rel(root, chosen)
    if not rpath.is_file():
        raise GateRefused(f"review not found: {rrel}", "review_missing")
    rtext = rpath.read_text(encoding="utf-8")
    rfm = front_matter(rtext)
    if rfm.get("gate") and rfm["gate"] != gate:
        raise GateRefused(f"{rrel}: review gate is '{rfm['gate']}', expected '{gate}'", "wrong_gate")
    version, signed_on = rfm.get("version", "").strip(), fm.get("review_version", "").strip()
    if not version or not signed_on or version != signed_on:
        raise GateRefused(f"{rel}: signed on review version '{signed_on or '?'}' but {rrel} is at version "
                          f"'{version or '?'}' — both are required and must match (process the targeted "
                          f"re-review first)", "stale_verdict")
    all_findings = review_findings(rtext)
    # feature gate: a role verdict decides only the findings assigned to its role (D27); a decision it records on
    # another role's finding is informative only (neither required, nor checked, nor turned into debt)
    findings = findings_for_role(rtext, role) if g.roles else all_findings
    decisions = {i: d for i, d in verdict_decisions(text).items()
                 if i.startswith("H") or i in findings or i not in all_findings}
    who = f" (role {role})" if role else ""
    missing = [f for f in findings if f not in decisions]
    if missing:
        raise GateRefused(f"{rel}: findings without a decision{who}: {', '.join(missing)}", "undecided")
    unknown = [i for i in decisions if not i.startswith("H") and i not in findings]
    if unknown:
        raise GateRefused(f"{rel}: decisions on unknown findings: {', '.join(unknown)}", "unknown_finding")
    pending = [i for i, (d, _) in decisions.items() if d not in FINAL_DECISIONS]
    if pending:
        raise GateRefused(f"{rel}: undecided findings{who} (discuss or unknown decision): {', '.join(pending)}",
                          "undecided")
    unexplained = [i for i, (d, why) in decisions.items() if d in NEEDS_REASON and not why]
    if unexplained:
        raise GateRefused(f"{rel}: rejected/bypassed without a reason: {', '.join(unexplained)}", "missing_reason")
    return Verdict(path=rel, ref=blob_ref(vpath), review=rrel, review_ref=blob_ref(rpath), review_version=version,
                   outcome=outcome, signed_by=signed_by, signed_at=fm["signed_at"].strip(), role=role,
                   decisions=decisions)


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
            raise GateRefused(f"{g.command}: the feature gate targets an epic, '{target}' is a story",
                              "not_an_epic")
        members = [t for t in tickets if t.epic == target and not t.supersededBy]
        if not members:
            raise GateRefused(f"{g.command}: unknown epic '{target}'", "not_an_epic")
        floor = _index(g.source)
        lagging = [f"{t.id} ({t.status})" for t in members if _index(t.status) < floor]
        if lagging:
            raise GateRefused(f"{g.command}: every story of {target} must be {g.source} first — "
                              f"not yet: {', '.join(lagging)}", "bad_state")
        found = [t for t in members if t.status == g.source]
        if not found:
            raise GateRefused(f"{g.command}: no story of {target} in {g.source}", "bad_state")
        return found
    if target in by_id:
        t = by_id[target]
        if t.status != g.source:
            raise GateRefused(f"{g.command}: {target} is {t.status}, expected {g.source}", "bad_state")
        return [t]
    found = [t for t in tickets if t.epic == target and t.status == g.source]
    if not found:
        raise GateRefused(f"{g.command}: '{target}' is neither a story nor an epic with stories in {g.source}",
                          "bad_state")
    return found


def _now(now: str | None) -> str:
    return now or datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_verdict(g: Gate, epic: str, role: str | None) -> str:
    """`<EPIC>/review-<gate>-verdict[-<role>].md` — where an epic-level verdict lives."""
    stem = g.review_file.removesuffix(".md")
    return f"{epic}/{stem}-verdict{f'-{role}' if role else ''}.md"


def debt_tag(gate: str, target: str, finding: str, role: str | None) -> str:
    return f"[{gate} {target} {role} {finding}]" if role else f"[{gate} {target} {finding}]"


def run_gate(sdlc, gate: str, target: str, verdicts: list[str] | None, review: str | None = None,
             signers: list[str] | None = None, now: str | None = None) -> dict:
    """Check everything, then record the gate. A `GateRefused` leaves the workspace untouched."""
    g = GATES[gate]
    root = Path(sdlc.ws.root)
    if not verdicts:
        raise GateRefused(f"{g.command}: --verdict <path> is required — the gate rests on a verdict signed by a "
                          f"human (review by harry-archi, then /process-review)", "verdict_missing")
    if not g.roles and len(verdicts) > 1:
        raise GateRefused(f"{g.command}: one verdict per spec gate", "duplicate_role")
    targets = _targets(sdlc, g, target)
    checked = [check_verdict(root, v, gate, target, review, signers) for v in verdicts]

    # --- decide (still read-only) ---
    by_role: dict[str | None, Verdict] = {}
    for v in checked:
        if v.role in by_role:
            raise GateRefused(f"{g.command}: two verdicts for the same role '{v.role}'", "duplicate_role")
        by_role[v.role] = v
    earlier: dict[str, Verdict] = {}
    for role in g.roles:
        if role in by_role:
            continue
        candidates = [canonical_verdict(g, target, role), targets[0].artifacts.get(g.verdict_kind_for(role))]
        for candidate in dict.fromkeys(c for c in candidates if c):
            try:
                earlier[role] = check_verdict(root, candidate, gate, target, None, signers)
                break
            except GateRefused:
                continue  # a verdict that no longer holds (e.g. back to draft) counts as missing
    present = {**by_role, **earlier}
    waiting = [r for r in g.roles if r not in present]
    outcome = max((v.outcome for v in present.values()), key=_OUTCOME_RANK.__getitem__)
    advance = not waiting and outcome in ADVANCING

    # --- write: debt (only when the gate advances), then links + journal + transition per story ---
    debt: list[str] = []
    if advance:
        store = PostMortemStore(root)
        story = target if len(targets) == 1 and targets[0].id == target else None
        for v in present.values():
            for fid, (decision, why) in v.decisions.items():
                if decision not in DEBT_DECISIONS:
                    continue
                tag = debt_tag(gate, target, fid, v.role)
                known = next((i for i in store.list(kind="debt") if i.text.startswith(tag)), None)
                if known is None:
                    known = store.add(agent="human", kind="debt", severity=severity_of(fid), epic=targets[0].epic,
                                      story=story, text=f"{tag} {decision}: {why or 'no reason given'} "
                                                        f"(verdict {v.path}, signed by {v.signed_by})")
                if known.id not in debt:
                    debt.append(known.id)

    signers_txt = ", ".join(v.signed_by + (f" ({v.role})" if v.role else "") for v in present.values())
    if advance:
        head = f"GATE {gate}  {g.source} -> {g.dest}  ({outcome}, signé par: {signers_txt})"
    elif waiting:
        head = (f"GATE {gate}  verdict {', '.join(r for r in by_role if r)} enregistré ({outcome}, signé par: "
                f"{signers_txt}) — attend: {', '.join(waiting)}")
    else:
        head = f"GATE {gate}  {outcome} (signé par: {signers_txt}) — pas de transition, retour en correction"
    lines = [f"## {_now(now)} — {head}"]
    for review_path, review_ref, review_version in dict.fromkeys(
            (v.review, v.review_ref, v.review_version) for v in present.values()):
        lines.append(f"review: {review_path}@{review_ref} (v{review_version})")
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
        "advanced": advanced,
        "validated": advanced,  # output key of the pre-0.8.0 validate-func/validate-spec, kept for scripts
        "recorded": [t.id for t in targets], "waiting": waiting,
        "review": checked[0].review,
        "verdicts": {(v.role or gate): f"{v.path}@{v.ref}" for v in present.values()},
        "debt": debt,
    }
