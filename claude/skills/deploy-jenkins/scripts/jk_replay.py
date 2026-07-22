#!/usr/bin/env python3
"""Déclenche un build Jenkins en overridant CODE_BRANCH via **Replay** (job dont la branche est figée
dans le Jenkinsfile/mainScript). Sortie JSON `{ok, build, code_branch}`.

    python3 jk_replay.py --jenkins https://ci… --job prod/app/ci --from 116 --code-branch feat/x

Logique pure (testée offline) : `extract_main_script`, `swap_code_branch`, `job_url`.
"""
from __future__ import annotations

import argparse
import html as _html
import re
import sys
import time

from _deploy_common import curl_json, curl_text, die, emit, job_url, post


def extract_main_script(form_html: str) -> str:
    """Extrait le contenu du textarea `_.mainScript` du formulaire /replay/."""
    m = re.search(r'name="_\.mainScript"[^>]*>(.*?)</textarea>', form_html, re.S)
    if not m:
        raise ValueError("mainScript introuvable dans le formulaire replay")
    return _html.unescape(m.group(1))


def swap_code_branch(main_script: str, branch: str) -> str:
    """Remplace la valeur liée à CODE_BRANCH dans le mainScript Groovy (2 ordres possibles)."""
    p1 = re.compile(r"(name:\s*'CODE_BRANCH'\s*,\s*value:\s*')([^']*)(')")
    out, n = p1.subn(lambda m: m.group(1) + branch + m.group(3), main_script)
    if n:
        return out
    p2 = re.compile(r"(value:\s*')([^']*)('\s*,\s*name:\s*'CODE_BRANCH')")
    out, n = p2.subn(lambda m: m.group(1) + branch + m.group(3), main_script)
    if n:
        return out
    raise ValueError("CODE_BRANCH introuvable dans le mainScript")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="jk_replay.py")
    ap.add_argument("--jenkins", required=True)
    ap.add_argument("--job", required=True, help="ex. prod/app/ci")
    ap.add_argument("--from", dest="frm", required=True, help="build à rejouer (ex. 116)")
    ap.add_argument("--code-branch", required=True)
    a = ap.parse_args(argv)

    base = a.jenkins.rstrip("/") + job_url(a.job)
    try:
        script = swap_code_branch(extract_main_script(curl_text(f"{base}/{a.frm}/replay/")), a.code_branch)
    except ValueError as e:
        die(str(e))
    code = post(f"{base}/{a.frm}/replay/run", a.jenkins, [("mainScript", script), ("script", "")])
    if code not in ("200", "201", "302"):
        die(f"POST replay/run → HTTP {code}")
    time.sleep(3)  # laisse le build entrer dans la queue
    lb = curl_json(f"{base}/api/json?tree=lastBuild[number]").get("lastBuild", {}).get("number")
    emit({"ok": True, "build": lb, "code_branch": a.code_branch})


if __name__ == "__main__":
    sys.exit(main())
