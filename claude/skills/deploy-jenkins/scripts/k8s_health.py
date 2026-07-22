#!/usr/bin/env python3
"""Santé d'un service déployé : `kubectl port-forward` + `curl` health. Sortie JSON `{ok, http, status}`.

    python3 k8s_health.py --ns hia-tenant --deploy hia-back-tenant-ht --remote-port 8088 --path /actuator/health

Le port-forward est ouvert PUIS refermé par le script (rien ne fuit ; pas de process orphelin).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

from _deploy_common import emit


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="k8s_health.py")
    ap.add_argument("--ns", required=True)
    ap.add_argument("--deploy", required=True)
    ap.add_argument("--remote-port", default="8088")
    ap.add_argument("--local-port", default="18088")
    ap.add_argument("--path", default="/actuator/health")
    a = ap.parse_args(argv)

    pf = subprocess.Popen(
        ["kubectl", "-n", a.ns, "port-forward", f"deploy/{a.deploy}", f"{a.local_port}:{a.remote_port}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(3)
        base = f"http://localhost:{a.local_port}{a.path}"
        http = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", base],
                              capture_output=True, text=True).stdout.strip()
        body = subprocess.run(["curl", "-s", base], capture_output=True, text=True).stdout
        status = None
        try:
            status = json.loads(body).get("status")
        except Exception:
            pass
        emit({"ok": http == "200" and status in (None, "UP"), "http": http, "status": status})
    finally:
        pf.terminate()


if __name__ == "__main__":
    sys.exit(main())
