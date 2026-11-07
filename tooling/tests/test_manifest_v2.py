"""The run manifest, v2: one shape to write, one door to read, both versions behind it.

Pure unit tests — no workspace, no git, no backend. What they guard is the part of the story a
workspace test cannot see cheaply: that v1 and v2 normalise to the SAME internal shape, that an
unknown version is refused by name instead of read halfway, and that the tolerance to additive keys
is a property of the reader rather than a property of any particular field.
"""
from __future__ import annotations

import pytest

from sdlc.runws.model import (MANIFEST_SCHEMA_VERSION, MANIFEST_VERSIONS, SCHEMA_VERSION,
                              BrainRef, Manifest, RepoRef, RunError, read_manifest)

DOC = {"key": "feature/prd.md", "version": "v1", "sha256": "a" * 64, "size": 3, "origin": "x.md"}


def _v2(**over) -> dict:
    base = {
        "schema_version": 2, "run_uid": "20261107-101010-abcdef",
        "scope": {"feature": "F", "story": "F-1", "mission": None},
        "brain": {"repo": "/srv/brain", "branch": "main", "commit": "c" * 40},
        "files": [DOC],
        "repos": [{"repo": "api", "branch": "feat/x", "commit": "t" * 40, "role": "target"},
                  {"repo": "web", "branch": "main", "commit": "n" * 40, "role": "neighbour"}],
        "dirty": [], "warnings": [],
    }
    base.update(over)
    return base


# --- the two versions are distinct, and that is the point ---

def test_the_manifest_version_is_not_the_run_json_version() -> None:
    """Bumping the shared constant would have moved every run.json to 2 without saying so — light
    runs included, which this story does not touch."""
    assert SCHEMA_VERSION == 1
    assert MANIFEST_SCHEMA_VERSION == 2
    assert MANIFEST_VERSIONS == (1, 2)


# --- v2 ---

def test_v2_reads_back_exactly_what_it_says() -> None:
    m = read_manifest(_v2())
    assert m.schema_version == 2
    assert m.brain == BrainRef(repo="/srv/brain", branch="main", commit="c" * 40)
    assert list(m.files) == ["feature/prd.md"]
    assert m.repos == [RepoRef("api", "feat/x", "t" * 40, "target"),
                       RepoRef("web", "main", "n" * 40, "neighbour")]


def test_only_neighbours_are_subtree_roots() -> None:
    """A target lives under `rw/code/` and is meant to move; pruning it from the `in/` walk would
    prune nothing, and listing it as a subtree root would be a lie about where it is."""
    assert read_manifest(_v2()).subtree_roots == {"repos/web"}


# --- v1 reads back into the same shape ---

def test_v1_neighbours_become_repos_and_leave_files() -> None:
    v1 = {"schema_version": 1, "run_uid": "u", "scope": {"story": "F-1"},
          "files": [DOC, {"key": "repos/web", "commit": "n" * 40, "role": "neighbour"}],
          "brain": {"ref": "main", "commit": "c" * 40}, "dirty": []}
    m = read_manifest(v1)
    assert list(m.files) == ["feature/prd.md"], "a neighbour stayed among the documents"
    assert m.repos == [RepoRef("web", "", "n" * 40, "neighbour")]
    assert m.subtree_roots == {"repos/web"}


def test_v1_has_no_target_and_that_absence_is_faithful() -> None:
    """v1 had nowhere to put the target: its starting commit only ever reached `code.json`. Reading
    one back must not invent it."""
    v1 = {"schema_version": 1, "files": [{"key": "repos/web", "commit": "n" * 40}], "brain": None}
    assert [r.role for r in read_manifest(v1).repos] == ["neighbour"]


def test_a_v1_brain_keeps_its_branch_under_the_new_name() -> None:
    m = read_manifest({"schema_version": 1, "brain": {"ref": "main", "commit": "c" * 40}})
    assert m.brain == BrainRef(repo="", branch="main", commit="c" * 40)


def test_an_absent_version_reads_as_v1() -> None:
    """A manifest written before the key existed is a v1, not an unknown."""
    m = read_manifest({"files": [DOC]})
    assert m.schema_version == 1 and list(m.files) == ["feature/prd.md"]


def test_a_bare_list_is_the_historical_light_manifest() -> None:
    m = read_manifest([DOC])
    assert m.schema_version == 1 and list(m.files) == ["feature/prd.md"]
    assert m.repos == [] and m.brain is None


# --- refusals and tolerance ---

@pytest.mark.parametrize("version", [0, 3, 99, "2", None])
def test_an_unknown_version_is_refused_by_name(version) -> None:
    """Never a partial read: an engine that cannot name what it is reading has to stop."""
    with pytest.raises(RunError) as e:
        read_manifest({"schema_version": version, "files": []})
    assert e.value.code == "manifest_unsupported"


def test_an_unknown_key_is_ignored_rather_than_refused() -> None:
    """THE decision of D9, and it is the rule that is decided, not any one field: a reader ignores
    what it does not know, so a future additive key needs no new manifest version."""
    m = read_manifest(_v2(futur="whatever", brain={"repo": "r", "branch": "b",
                                                   "commit": "c" * 40, "extra": 1}))
    assert m.brain == BrainRef(repo="r", branch="b", commit="c" * 40)
    assert list(m.files) == ["feature/prd.md"]


# --- brain: three fields or nothing ---

@pytest.mark.parametrize("brain", [None, {}, {"branch": "main"}, {"repo": "r", "commit": ""}])
def test_a_brain_without_a_commit_is_no_brain_at_all(brain) -> None:
    """I6: never a branch without its commit. A half-filled reference would read as a pin that it
    is not."""
    assert read_manifest(_v2(brain=brain)).brain is None


def test_a_manifest_with_no_repository_is_legitimate() -> None:
    m = read_manifest(_v2(repos=[]))
    assert m.repos == [] and m.subtree_roots == set()


def test_what_is_not_a_manifest_at_all_is_refused() -> None:
    with pytest.raises(RunError) as e:
        read_manifest("not a manifest")
    assert e.value.code == "manifest_unsupported"


def test_the_internal_shape_has_no_version_specific_field() -> None:
    """Readers must not be able to branch on the version by accident: the normalised object exposes
    the same attributes whichever version produced it."""
    v1 = read_manifest({"schema_version": 1, "files": [DOC]})
    v2 = read_manifest(_v2())
    assert set(vars(v1)) == set(vars(v2)) == set(vars(Manifest(2, None, {}, None)))
