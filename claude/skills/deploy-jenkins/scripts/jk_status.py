#!/usr/bin/env python3
"""État d'un build Jenkins (poll). Sortie JSON `{ok, number, building, result}`.

    python3 jk_status.py --jenkins https://ci… --job prod/app/ci --build 117
"""
from __future__ import annotations

import argparse
import sys

from _common import curl_json, emit, job_url


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="jk_status.py")
    ap.add_argument("--jenkins", required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--build", required=True)
    a = ap.parse_args(argv)
    base = a.jenkins.rstrip("/") + job_url(a.job)
    d = curl_json(f"{base}/{a.build}/api/json?tree=number,building,result")
    emit({"ok": bool(d), "number": d.get("number"),
          "building": d.get("building"), "result": d.get("result")})


if __name__ == "__main__":
    sys.exit(main())
