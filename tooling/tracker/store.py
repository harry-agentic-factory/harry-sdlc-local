"""Pure logic of the tracker bridge: persistence, card lifecycle, card <-> story links, push plan.

No network, no subprocess here — the tracker source and the story-status lookup are injected, so every
rule is testable offline.

Card lifecycle (field `state`):
    new         seen on the board, nothing done yet
    instructed  an investigation file (`fiche`) exists
    reviewed    the human decided on it during /bugs-review (field `decision`)
    planned     linked to one or more SDLC stories
A card is never deleted from links.json: a card that left the board is flagged `gone`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

SCHEMA_VERSION = 1
STATES = ("new", "instructed", "reviewed", "planned")
# Review decisions (same spirit as /process-review, adapted to bugs).
DECISIONS = ("fix", "other", "deferred", "rejected", "superseded")
DECISIONS_NEEDING_REASON = ("other", "deferred", "rejected", "superseded")

# SDLC pipeline order, used to pick the least advanced story of a card.
PIPELINE = [
    "draft", "spec_func", "spec_func_validated", "spec_tech", "spec_validated", "feature_validated",
    "implemented", "reviewed", "deployed", "recette_ok", "accepted", "done",
]
# SDLC status -> tracker list, as seen by the reporter.
DEFAULT_STATUS_TO_LIST = {
    "draft": "TODO",
    "spec_func": "TODO",
    "spec_func_validated": "IN PROGRESS",
    "spec_tech": "IN PROGRESS",
    "spec_validated": "IN PROGRESS",
    "feature_validated": "IN PROGRESS",
    "implemented": "IN PROGRESS",
    "reviewed": "IN PROGRESS",
    "deployed": "IN PROGRESS",
    "recette_ok": "TOVALIDATE",
    "accepted": "VALIDATED",
    "done": "VALIDATED",
}
DEFAULT_LIST_ORDER = ["Backlog", "TODO", "IN PROGRESS", "TOVALIDATE", "VALIDATED"]

_SHORT_URL = re.compile(r"/c/([A-Za-z0-9]+)")

StoryStatus = Callable[[str], Optional[str]]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def card_ref(ref: str) -> str:
    """Normalise a card URL / shortLink / long id into what the tracker API accepts."""
    m = _SHORT_URL.search(ref)
    return m.group(1) if m else ref.strip()


def _later(a: Optional[str], b: Optional[str]) -> bool:
    """True when timestamp a is strictly after b. ISO strings of mixed offsets are compared as datetimes."""
    if not a or not b:
        return False
    parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    return parse(a) > parse(b)


@dataclass
class Tracker:
    root: Path
    config: dict
    links: dict = field(default_factory=dict)

    # ---- persistence -------------------------------------------------------------------------
    @classmethod
    def load(cls, root: Path) -> "Tracker":
        cfg_path = root / "config.json"
        if not cfg_path.exists():
            raise FileNotFoundError(f"{cfg_path} missing — run `tracker --project <P> init` first")
        config = json.loads(cfg_path.read_text())
        links_path = root / "links.json"
        links = json.loads(links_path.read_text()) if links_path.exists() else {
            "schemaVersion": SCHEMA_VERSION, "lastPull": None, "cards": {}}
        return cls(root, config, links)

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "links.json").write_text(
            json.dumps(self.links, indent=2, ensure_ascii=False, sort_keys=True) + "\n")

    @staticmethod
    def build_config(tracker_block: dict) -> dict:
        """Tracker config from a manifest `tracker` block: comment keys (`_*`) dropped, defaults added."""
        cfg = {k: v for k, v in tracker_block.items() if not k.startswith("_")}
        cfg.setdefault("statusToList", dict(DEFAULT_STATUS_TO_LIST))
        cfg.setdefault("listOrder", list(DEFAULT_LIST_ORDER))
        cfg["schemaVersion"] = SCHEMA_VERSION
        return cfg

    # ---- lookup -------------------------------------------------------------------------------
    @property
    def cards(self) -> dict:
        return self.links["cards"]

    def list_name(self, list_id: str) -> str:
        for name, lid in self.config.get("lists", {}).items():
            if lid == list_id:
                return name
        return list_id

    def nature(self, card: dict) -> Optional[str]:
        """bug | evol | None. An explicit label wins over the intake list the card sits in."""
        natures = set(self.config.get("intake", {}).values())
        for label in card.get("labels", []):
            if label in natures:
                return label
        return self.config.get("intake", {}).get(card.get("list"))

    def find(self, ref: str) -> tuple[str, dict]:
        ref = card_ref(ref)
        if ref in self.cards:
            return ref, self.cards[ref]
        for cid, c in self.cards.items():
            if c.get("shortLink") == ref:
                return cid, c
        raise KeyError(f"card {ref} unknown — run `tracker pull` first")

    def select(self, state: Optional[str] = None, story: Optional[str] = None,
               nature: Optional[str] = None, include_gone: bool = False) -> list[dict]:
        out = []
        for cid, c in self.cards.items():
            if c.get("gone") and not include_gone:
                continue
            if state and c.get("state") != state:
                continue
            if story and story not in c.get("stories", []):
                continue
            if nature and self.nature(c) != nature:
                continue
            out.append({"card": cid, "nature": self.nature(c), **c})
        return sorted(out, key=lambda c: (c.get("list") or "", c.get("name") or ""))

    # ---- pull: tracker -> links.json ----------------------------------------------------------
    def merge_pull(self, remote: Iterable[dict], at: Optional[str] = None) -> dict:
        """Upsert the board's open cards. Returns what needs attention; never forgets a card."""
        at = at or now_iso()
        intake = set(self.config.get("intake", {}))
        seen: set[str] = set()
        report = {"new": [], "changed": [], "gone": [], "toInstruct": [], "toReview": []}
        for r in remote:
            cid = r["id"]
            seen.add(cid)
            fresh = {
                "shortLink": r.get("shortLink"),
                "url": r.get("shortUrl") or r.get("url"),
                "name": r.get("name"),
                "list": self.list_name(r.get("idList", "")),
                "labels": sorted(lb["name"] for lb in r.get("labels", []) if lb.get("name")),
                "dateLastActivity": r.get("dateLastActivity"),
                "gone": False,
            }
            entry = self.cards.get(cid)
            if entry is None:
                entry = {"state": "new", "firstSeenAt": at, "fiche": None, "instructedAt": None,
                         "decision": None, "reason": None, "decidedAt": None, "review": None,
                         "epic": None, "stories": [], "lastPushedList": None}
                self.cards[cid] = entry
                report["new"].append(cid)
            else:
                # A card edited after it was instructed or decided must be looked at again.
                last_handled = entry.get("decidedAt") or entry.get("instructedAt")
                if _later(fresh["dateLastActivity"], last_handled):
                    report["changed"].append(cid)
            entry.update(fresh)
        for cid, entry in self.cards.items():
            if cid not in seen:
                if not entry.get("gone"):
                    entry["gone"] = True
                    report["gone"].append(cid)
                continue
            if entry["state"] == "new" and (not intake or entry["list"] in intake):
                report["toInstruct"].append(cid)
            elif entry["state"] == "instructed":
                report["toReview"].append(cid)
        self.links["lastPull"] = at
        return report

    # ---- lifecycle transitions ----------------------------------------------------------------
    def instructed(self, ref: str, fiche: str, at: Optional[str] = None) -> dict:
        cid, c = self.find(ref)
        c["fiche"], c["instructedAt"] = fiche, at or now_iso()
        if c["state"] in ("new", "instructed"):
            c["state"] = "instructed"
        return {"card": cid, **c}

    def decide(self, ref: str, decision: str, reason: Optional[str] = None,
               review: Optional[str] = None, at: Optional[str] = None) -> dict:
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {'|'.join(DECISIONS)}, got {decision!r}")
        if decision in DECISIONS_NEEDING_REASON and not reason:
            raise ValueError(f"decision {decision!r} needs a reason")
        cid, c = self.find(ref)
        c["decision"], c["reason"], c["decidedAt"] = decision, reason, at or now_iso()
        if review:
            c["review"] = review
        if c["state"] != "planned":
            c["state"] = "reviewed"
        return {"card": cid, **c}

    def link(self, ref: str, story: str, epic: Optional[str] = None) -> dict:
        cid, c = self.find(ref)
        if c.get("decision") not in ("fix", "other"):
            raise ValueError(f"card {c.get('shortLink')} has decision {c.get('decision')!r}: "
                             "only a card decided `fix` or `other` becomes a story")
        if story not in c["stories"]:
            c["stories"].append(story)
        if epic:
            c["epic"] = epic
        c["state"] = "planned"
        return {"card": cid, **c}

    # ---- push plan: SDLC -> tracker -----------------------------------------------------------
    def plan(self, status_of: StoryStatus) -> dict:
        """List moves implied by the SDLC. Only moves a card FORWARD; anything else is a signal."""
        order = self.config.get("listOrder", DEFAULT_LIST_ORDER)
        mapping = self.config.get("statusToList", DEFAULT_STATUS_TO_LIST)
        moves, signals = [], []
        for cid, c in self.cards.items():
            if c.get("state") != "planned" or c.get("gone"):
                continue
            statuses = {s: status_of(s) for s in c["stories"]}
            known = [v for v in statuses.values() if v in PIPELINE]
            base = {"card": cid, "shortLink": c.get("shortLink"), "name": c.get("name"),
                    "stories": statuses, "from": c.get("list")}
            if len(known) != len(statuses):
                signals.append({**base, "kind": "unknown-story"})
                continue
            least = min(known, key=PIPELINE.index)  # a card is as far as its least advanced story
            target = mapping.get(least)
            current = c.get("list")
            item = {**base, "status": least, "to": target}
            if target is None or current == target:
                continue
            if current not in order or target not in order:
                signals.append({**item, "kind": "unmapped-list"})
            elif order.index(current) > order.index(target):
                accepted = current == order[-1] and least == "recette_ok"
                signals.append({**item, "kind": "reporter-accepted" if accepted else "card-ahead-of-story"})
            elif c.get("lastPushedList") == target:
                # We already moved it there and a human moved it back: that is feedback, not drift.
                signals.append({**item, "kind": "sent-back-by-human"})
            else:
                moves.append(item)
        return {"moves": moves, "signals": signals}

    def mark_pushed(self, card_id: str, list_name: str) -> None:
        self.cards[card_id]["list"] = list_name
        self.cards[card_id]["lastPushedList"] = list_name
