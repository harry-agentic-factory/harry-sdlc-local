"""DAG des stories : ordre topologique + prochaines stories actionnables.

`deps[story] = [stories dont elle dépend]`. Un cycle (A→B→A) n'est pas un DAG
et lève `CycleError` : c'est ce qui garantit qu'un plan de /refine est exécutable.
"""
from __future__ import annotations

from collections import deque


class CycleError(ValueError):
    pass


def topo_order(deps: dict[str, list[str]]) -> list[str]:
    """Kahn — ordre déterministe (tri lexical à chaque étape pour la reproductibilité)."""
    indeg: dict[str, int] = {n: 0 for n in deps}
    adj: dict[str, list[str]] = {n: [] for n in deps}
    for n, ds in deps.items():
        for d in ds:
            if d not in deps:
                raise CycleError(f"dépendance inconnue: {n} -> {d}")
            indeg[n] += 1        # arête d -> n
            adj[d].append(n)

    q: deque[str] = deque(sorted(n for n, i in indeg.items() if i == 0))
    order: list[str] = []
    while q:
        n = q.popleft()
        order.append(n)
        for m in sorted(adj[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)

    if len(order) != len(deps):
        stuck = sorted(n for n in deps if n not in order)
        raise CycleError(f"cycle détecté (pas un DAG): {stuck}")
    return order


def next_actionable(
    deps: dict[str, list[str]],
    statuses: dict[str, str],
    done_states: frozenset[str] | set[str] = frozenset({"done", "accepted"}),
) -> list[str]:
    """Stories prêtes à démarrer : pas terminées, et toutes leurs deps terminées."""
    ready: list[str] = []
    for n in topo_order(deps):
        if statuses.get(n) in done_states:
            continue
        if all(statuses.get(d) in done_states for d in deps.get(n, [])):
            ready.append(n)
    return ready
