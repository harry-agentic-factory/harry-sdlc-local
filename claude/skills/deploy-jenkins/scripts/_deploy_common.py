"""Helpers partagés des outils deploy-jenkins. Stdlib only.

Auth = `curl -s -n` (.netrc) exécuté EN INTERNE (jamais de secret affiché, jamais `-L`). Les appels réseau
/kubectl sont des sous-process de CE script → une seule autorisation (le script) suffit, rien n'est
re-prompté. Sorties = JSON compact sur stdout (filtré, < 2 Ko).
"""
from __future__ import annotations

import json
import subprocess
import sys


def job_url(job_path: str) -> str:
    """`prod/app/ci` → `/job/prod/job/app/job/ci` (chemin de job Jenkins avec folders)."""
    return "".join("/job/" + p for p in job_path.strip("/").split("/") if p)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def curl_text(url: str) -> str:
    """GET Jenkins en `curl -s -n` (jamais `-L`)."""
    return _run(["curl", "-s", "-n", url]).stdout


def curl_json(url: str) -> dict:
    try:
        return json.loads(curl_text(url) or "{}")
    except Exception:
        return {}


def crumb(jenkins: str) -> tuple[str | None, str | None]:
    d = curl_json(jenkins.rstrip("/") + "/crumbIssuer/api/json")
    return (d.get("crumbRequestField"), d.get("crumb"))


def post(url: str, jenkins: str, data: list[tuple[str, str]] | None = None) -> str:
    """POST Jenkins avec crumb CSRF. Retourne le code HTTP (str). Jamais `-L`."""
    field, val = crumb(jenkins)
    cmd = ["curl", "-s", "-n", "-o", "/dev/null", "-w", "%{http_code}", "-X", "POST"]
    if field:
        cmd += ["-H", f"{field}:{val}"]
    for k, v in (data or []):
        cmd += ["--data-urlencode", f"{k}={v}"]
    cmd += [url]
    return _run(cmd).stdout.strip()


def kubectl(args: list[str]) -> subprocess.CompletedProcess:
    return _run(["kubectl", *args])


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def die(msg: str) -> None:
    emit({"ok": False, "error": msg})
    sys.exit(1)
