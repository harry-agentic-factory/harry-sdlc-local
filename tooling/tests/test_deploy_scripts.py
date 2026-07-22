"""Outils normalisés du skill deploy-jenkins — logique PURE (offline), celle que le deployer improvisait.
Les parties réseau/kubectl (main()) ne sont pas testées ici (nécessitent l'infra) ; seule la logique
déterministe l'est : job_url, extract_main_script, swap_code_branch (les 2 ordres), parse_image_tag.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "claude" / "skills" / "deploy-jenkins" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _common import job_url          # noqa: E402
import jk_replay                     # noqa: E402
import k8s_version                   # noqa: E402


def test_job_url():
    assert job_url("prod/hia-back-tenant/ci") == "/job/prod/job/hia-back-tenant/job/ci"
    assert job_url("/prod/app/ci/") == "/job/prod/job/app/job/ci"


def test_swap_code_branch_both_orders():
    assert jk_replay.swap_code_branch("[name: 'CODE_BRANCH', value: 'feat/old']", "feat/new") \
        == "[name: 'CODE_BRANCH', value: 'feat/new']"
    assert jk_replay.swap_code_branch("[value: 'feat/old', name: 'CODE_BRANCH']", "feat/new") \
        == "[value: 'feat/new', name: 'CODE_BRANCH']"


def test_swap_code_branch_absent_raises():
    with pytest.raises(ValueError):
        jk_replay.swap_code_branch("aucun paramètre ici", "x")


def test_extract_main_script_unescapes():
    html = '<textarea name="_.mainScript" rows="8">node {\n  echo &#39;hi&#39;\n}</textarea>'
    out = jk_replay.extract_main_script(html)
    assert "node {" in out and "'hi'" in out


def test_extract_main_script_absent_raises():
    with pytest.raises(ValueError):
        jk_replay.extract_main_script("<html>pas de textarea</html>")


def test_parse_image_tag():
    assert k8s_version.parse_image_tag("acr.azurecr.io/hia-back-tenant:1.0.0-117") \
        == ("acr.azurecr.io/hia-back-tenant", "1.0.0-117")
    assert k8s_version.parse_image_tag("nginx") == ("nginx", None)
