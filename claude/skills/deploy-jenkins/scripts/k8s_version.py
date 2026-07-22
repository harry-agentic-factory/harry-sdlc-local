#!/usr/bin/env python3
"""Image/tag actuellement déployé pour un Deployment k8s. Sortie JSON `{ok, image, tag}`.

    python3 k8s_version.py --ns hia-tenant --deploy hia-back-tenant-ht [--container 0]
"""
from __future__ import annotations

import argparse
import sys

from _deploy_common import die, emit, kubectl


def parse_image_tag(image_ref: str) -> tuple[str, str | None]:
    """`registry/name:1.0.0-117` → (`registry/name`, `1.0.0-117`). Sans tag → (ref, None)."""
    last = image_ref.rsplit("/", 1)[-1]
    if ":" in last:
        name, tag = image_ref.rsplit(":", 1)
        return name, tag
    return image_ref, None


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="k8s_version.py")
    ap.add_argument("--ns", required=True)
    ap.add_argument("--deploy", required=True)
    ap.add_argument("--container", default="0")
    a = ap.parse_args(argv)
    jp = "{.spec.template.spec.containers[" + a.container + "].image}"
    cp = kubectl(["-n", a.ns, "get", "deploy", a.deploy, "-o", f"jsonpath={jp}"])
    if cp.returncode != 0 or not cp.stdout.strip():
        die(f"kubectl get deploy {a.deploy} (ns {a.ns}) → {cp.stderr.strip() or 'image vide'}")
    image, tag = parse_image_tag(cp.stdout.strip())
    emit({"ok": True, "image": image, "tag": tag})


if __name__ == "__main__":
    sys.exit(main())
