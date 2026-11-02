"""Is a maquette built with the project design system? (story -3)

The engine knows no token, no component name, no path: everything comes from the manifest. These tests therefore
build their own tiny socle, and replay the real maquettes only when the data repository is reachable.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdlc import maquette

REPO = Path(__file__).resolve().parents[2]
GUIDE = REPO / "docs" / "maquettes.md"
HARRY_ARCHI = REPO / "claude" / "agents" / "harry-archi.md"

TOKENS = ":root {\n  --ink: #1b1b1b;\n  --fs-13: 13px;\n  --fw-semibold: 600;\n  --r-md: 10px;\n}\n"

CONFORM = """<html><style id="ds" media="not all">
.ui-badge { color: #ff0000; font-size: 11px; }
</style><style id="new">
.cvw-meta { color: var(--ink); font-size: var(--fs-13); padding: 7px; }
</style><body><p class="cvw-meta">x</p></body></html>
"""

OFFENDING = """<html><style id="new">
.cvw-bad { color: #ff0000; font-size: 15px; font-weight: 550; padding: 7px; }
.cvw-unknown { color: var(--pas-un-jeton); }
.cvw-row > .ui-icon { opacity: 1; width: 2px; }
</style><body><div style="height: 120px">x</div><p style="color: #00ff00">y</p></body></html>
"""

NO_CONVENTION = "<html><style>\n.side { left: 13px; font-size: 13px; }\n</style><body>x</body></html>\n"


@pytest.fixture
def socle(tmp_path):
    (tmp_path / "tokens.css").write_text(TOKENS)
    ui = tmp_path / "ui"
    ui.mkdir()
    # Enough `ui-` classes for the prefix to be derived from the socle's own files, never hard-coded.
    (ui / "ui.css").write_text("".join(f".ui-c{i} {{ color: var(--ink); }}\n" for i in range(8)))
    return {"tokens": [str(tmp_path / "tokens.css")], "components": str(ui)}


def analyse(html: str, socle: dict, items=None, deviations: str = "") -> dict:
    return maquette.analyse_socle(html, maquette.tokens_of(socle["tokens"]),
                                  maquette.socle_prefix(socle["components"]), items, deviations)


def types_of(out: dict) -> list[str]:
    return [s["type"] for s in out["signalements"]]


# --- AC1: the manifest block -----------------------------------------------------------------------------------

def test_the_socle_block_is_resolved_and_optional(tmp_path, socle):
    from sdlc.config import load_config, resolved_manifest

    (tmp_path / "sdlc.config.json").write_text(json.dumps(
        {"prefix": "E", "repos": {"app": str(tmp_path)}, "socle": {"app": {"tokens": ["tokens.css"],
                                                                          "components": "ui"}}}))
    out = resolved_manifest(workspace=tmp_path)["socle"]["app"]
    assert set(out) == {"tokens", "components"}          # two keys, nothing else
    assert Path(out["tokens"][0]).is_absolute() and Path(out["components"]).is_absolute()

    bare = tmp_path / "bare"
    bare.mkdir()
    assert load_config(bare)["socle"] == {}
    assert resolved_manifest(workspace=bare)["socle"] == {}


# --- AC2 to AC7: the six types ---------------------------------------------------------------------------------

def test_a_conform_maquette_has_no_value_signal(socle):
    out = analyse(CONFORM, socle)
    assert [t for t in types_of(out) if t in ("couleur", "taille", "graisse", "jeton inconnu")] == []


def test_the_verbatim_block_is_never_controlled(socle):
    """The same hexadecimal: silent inside the design system copy, signalled once in the maquette's own rules."""
    assert "couleur" not in types_of(analyse(CONFORM, socle))
    moved = CONFORM.replace('.cvw-meta { color: var(--ink);', '.cvw-meta { color: #ff0000;')
    assert types_of(analyse(moved, socle)).count("couleur") == 1


def test_a_literal_colour_size_and_weight_are_signalled_but_not_a_spacing(socle):
    out = analyse(OFFENDING, socle)
    counted = [t for t in types_of(out) if t in ("couleur", "taille", "graisse")]
    assert sorted(set(counted)) == ["couleur", "graisse", "taille"]
    assert all("padding" not in s["valeur"] for s in out["signalements"]), "spacings are the practice of the socle"


def test_an_unknown_token_is_signalled(socle):
    assert "jeton inconnu" in types_of(analyse(OFFENDING, socle))


def test_an_inline_style_is_controlled_like_a_rule(socle):
    """An inline `style=` is analysed for the same value types as a rule — and a dimension in px is NOT one of
    them, no more there than in a rule: the manual verdict this automates had accepted exactly such a case."""
    out = analyse(OFFENDING, socle)
    inline = [s for s in out["signalements"] if s["sélecteur"] == "style="]
    assert [s["valeur"] for s in inline] == ["#00ff00"]
    assert all("120px" not in s["valeur"] for s in out["signalements"])


def test_a_declared_deviation_is_marked_as_such(socle):
    declared = analyse(OFFENDING, socle, deviations="la teinte #00ff00 du prototype — tranché par Anis")
    assert any(s["déclaré"] for s in declared["signalements"] if s["valeur"] == "#00ff00")


def test_a_new_rule_targeting_the_socle_is_signalled_once_per_rule(socle):
    out = analyse(OFFENDING, socle)
    hits = [s for s in out["signalements"] if s["type"] == "règle neuve visant le socle"]
    assert len(hits) == 1, "one finding per rule, whatever the number of declarations inside it"
    assert ".ui-icon" in hits[0]["valeur"]


def test_a_missing_mapping_is_signalled(socle):
    items = [maquette.Item("icones", "Icônes", "quatre pastilles", "Icon", None, False),
             maquette.Item("trait", "Trait", "pointillé", "—", None, False)]
    out = analyse(CONFORM, socle, items)
    hits = [s for s in out["signalements"] if s["type"] == "correspondance manquante"]
    assert [s["valeur"] for s in hits] == ["trait"]


# --- AC8 and AC10: no silent pass, and a shape that never changes ----------------------------------------------

def test_a_maquette_without_the_block_convention_says_so(socle):
    out = analyse(NO_CONVENTION, socle)
    assert out["règles neuves"] is None
    assert maquette.NO_BLOCK_CONVENTION in out["notes"]


def test_the_shape_never_changes(socle):
    keys = {"signalements", "règles neuves", "jetons connus", "notes"}
    for html in (CONFORM, OFFENDING, NO_CONVENTION):
        assert set(analyse(html, socle)) == keys
    # degradation goes to `notes`, never to a new key
    no_prefix = maquette.analyse_socle(CONFORM, maquette.tokens_of(socle["tokens"]), None)
    assert set(no_prefix) == keys and maquette.NO_SOCLE_PREFIX in no_prefix["notes"]


def test_without_a_derivable_prefix_the_socle_check_is_disabled(tmp_path):
    empty = tmp_path / "ui"
    empty.mkdir()
    assert maquette.socle_prefix(empty) is None
    assert maquette.socle_prefix(None) is None


def test_the_six_types_are_a_closed_list():
    assert len(maquette.SIGNAL_TYPES) == 6
    for signal_type in maquette.SIGNAL_TYPES:
        assert signal_type in GUIDE.read_text(encoding="utf-8"), signal_type


# --- AC9: no socle declared ------------------------------------------------------------------------------------

def test_a_repo_without_a_socle_is_a_usage_error(tmp_path, capsys, monkeypatch):
    from sdlc import cli

    (tmp_path / "sdlc.config.json").write_text(json.dumps({"prefix": "E"}))
    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path))
    maq = tmp_path / "m.html"
    maq.write_text(CONFORM)
    assert cli.main(["maquette", "socle", str(maq), "--repo", "app"]) == 2
    assert "aucun socle déclaré" in capsys.readouterr().out


# --- AC12 and AC13: the guide and the review mode --------------------------------------------------------------

def test_the_guide_carries_the_rules():
    text = GUIDE.read_text(encoding="utf-8")
    for key in ('<style id="ds">', '<style id="new">', "socle.", "espacements en px ne sont pas contrôlés",
                "à créer", "avec son commit"):
        assert key in text, key


def test_the_review_mode_has_its_fixed_format():
    section = HARRY_ARCHI.read_text(encoding="utf-8")
    mode = section.split("## Mode revue de maquette", 1)[1].split("\n## ", 1)[0]
    for key in ("kind: maquette-verdict", "validated_with_fixes", "returned", "## Synthèse", "## Décisions",
                "## Corrections de maquette", "## Sources", "avant le premier commit de code",
                "sdlc maquette socle"):
        assert key in mode, key
    assert "escalades" in mode or "escalade" in mode


# --- AC11 and AC15: the real maquettes, when the data repository is reachable -----------------------------------

DATA = Path("/Users/anisbessa/dev/workspace/harington-common/_wt/aisdlc-sdlc-local/docs-aisdlc-uifidelity")
REF = Path("/Users/anisbessa/dev/workspace/harington-common/_wt/harry-sdlc-ai-factory/ref-06a270d4")


@pytest.mark.skipif(not (DATA.is_dir() and REF.is_dir()),
                    reason="data repository or reference worktree not reachable")
def test_rejeu_agentconv():
    """The two conflicts the human verdict had found by hand (its decisions D1 and D12), and nothing else."""
    html = (DATA / "AISDLC-AGENTCONV" / "maquettes" / "agentconv-5-visualiseur.html").read_text(errors="replace")
    socle = {"tokens": [str(REF / "cockpit/src/v3/tokens.css")], "components": str(REF / "cockpit/src/v3/ui")}
    out = analyse(html, socle)
    assert [t for t in types_of(out) if t in ("couleur", "taille", "graisse", "jeton inconnu")] == []
    hits = sorted(s["valeur"] for s in out["signalements"] if s["type"] == "règle neuve visant le socle")
    assert len(hits) == 2
    assert any(".ui-badge" in h for h in hits) and any(".ui-icon" in h for h in hits)


@pytest.mark.skipif(not DATA.is_dir(), reason="data repository not reachable")
def test_the_validated_maquette_of_the_reference_case_cannot_be_analysed_silently():
    html = (DATA / "AISDLC-UIPOLISH" / "maquettes" / "nouvelle-feature-v7.html").read_text(errors="replace")
    out = maquette.analyse_socle(html, {"--ink"}, "ui")
    assert out["règles neuves"] is None and maquette.NO_BLOCK_CONVENTION in out["notes"]
