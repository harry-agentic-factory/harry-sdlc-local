"""Outils normalisés du skill recette (générique) — logique PURE offline (build_url, filter_obj).
Les parties réseau/port-forward (main) nécessitent l'infra ; l'auth spécifique projet vit dans un skill
projet (ex. hia-sdlc-local/skills/hia-recette). Le token n'est jamais en argv/sortie."""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "claude" / "skills" / "recette" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _recette_common import build_url, filter_obj   # noqa: E402


def test_build_url():
    assert build_url("http://localhost:18099", "/api/v1/applications") == "http://localhost:18099/api/v1/applications"
    assert build_url("http://h/", "x") == "http://h/x"


def test_filter_obj_list_and_dict():
    data = [{"clientId": "cfea", "enabled": True, "secret": "xxx"},
            {"clientId": "cfea-default", "enabled": False, "secret": "yyy"}]
    out = filter_obj(data, "clientId,enabled")
    assert out == [{"clientId": "cfea", "enabled": True}, {"clientId": "cfea-default", "enabled": False}]
    assert all("secret" not in x for x in out)      # champs non demandés écartés (contexte maigre + pas de secret)
    assert filter_obj({"a": 1, "b": 2}, "a") == {"a": 1}
    assert filter_obj(data, None) is data           # sans fields : inchangé
