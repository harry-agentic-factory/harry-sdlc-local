import pytest

from sdlc import topo_order, next_actionable, CycleError

# DAG repris de HIA-PROV : 1<-2,3 ; 4<-1 ; 5<-1,4 ; 6<-1 ; 7<-4,5,6
DEPS = {
    "1": ["2", "3"], "2": [], "3": [],
    "4": ["1"], "5": ["1", "4"], "6": ["1"], "7": ["4", "5", "6"],
}


def test_topo_respects_dependencies():
    order = topo_order(DEPS)
    pos = {n: i for i, n in enumerate(order)}
    for n, ds in DEPS.items():
        for d in ds:
            assert pos[d] < pos[n], f"{d} doit précéder {n}"


def test_next_actionable_starts_with_leaves():
    statuses = {n: "draft" for n in DEPS}
    # au départ, seules 2 et 3 sont actionnables (1 dépend d'elles)
    assert next_actionable(DEPS, statuses) == ["2", "3"]


def test_next_actionable_progresses():
    statuses = {n: "draft" for n in DEPS}
    statuses["2"] = statuses["3"] = "done"
    assert next_actionable(DEPS, statuses) == ["1"]
    statuses["1"] = "done"
    # 4 et 6 débloquées en parallèle (5 attend 4)
    assert next_actionable(DEPS, statuses) == ["4", "6"]


def test_cycle_is_detected():
    with pytest.raises(CycleError):
        topo_order({"a": ["b"], "b": ["a"]})
