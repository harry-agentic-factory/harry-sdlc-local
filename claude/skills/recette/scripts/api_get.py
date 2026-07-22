#!/usr/bin/env python3
"""GET authentifié vers un service déployé (générique). **Token lu d'un FICHIER, jamais affiché ni en argv**
(header via `curl -H @hdr`). Accès direct (`--base`) ou via port-forward (`--pf`). Sortie JSON filtrée.

    api_get.py --pf hia-tenant/deploy/hia-back-tenant-ht:8088 --path /api/v1/applications \
               --token-file <scratch>/token --fields clientId,enabled,authFlow,receptionMode

Logique pure testée offline : build_url, filter_obj. Le port-forward est ouvert PUIS refermé.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

from _common import build_url, die, emit, filter_obj


def _curl_get(url: str, token_file: str | None) -> str:
    args = ["curl", "-s", url]
    hdr = None
    if token_file:
        tok = open(token_file).read().strip()
        fd, hdr = tempfile.mkstemp()
        os.close(fd)
        with open(hdr, "w") as f:
            f.write("Authorization: Bearer " + tok)   # header dans un fichier -> jamais dans argv/ps
        os.chmod(hdr, 0o600)
        args = ["curl", "-s", "-H", "@" + hdr, url]
    try:
        return subprocess.run(args, capture_output=True, text=True).stdout
    finally:
        if hdr and os.path.exists(hdr):
            os.remove(hdr)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="api_get.py")
    ap.add_argument("--base", help="URL directe (sinon --pf)")
    ap.add_argument("--pf", help="port-forward : <ns>/<kind>/<name>:<remotePort>")
    ap.add_argument("--local-port", default="18099")
    ap.add_argument("--path", required=True)
    ap.add_argument("--token-file")
    ap.add_argument("--fields", help="CSV des champs à garder (contexte maigre)")
    a = ap.parse_args(argv)

    pf = None
    try:
        base = a.base
        if a.pf:
            ns, rest = a.pf.split("/", 1)
            target, remote = rest.rsplit(":", 1)
            pf = subprocess.Popen(["kubectl", "-n", ns, "port-forward", target, f"{a.local_port}:{remote}"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)
            base = f"http://localhost:{a.local_port}"
        if not base:
            die("ni --base ni --pf fourni")
        raw = _curl_get(build_url(base, a.path), a.token_file)
        try:
            data = json.loads(raw)
        except Exception:
            die("réponse non-JSON (auth invalide ? mauvais endpoint/port ?)")
        emit({"ok": True, "data": filter_obj(data, a.fields)})
    finally:
        if pf:
            pf.terminate()


if __name__ == "__main__":
    sys.exit(main())
