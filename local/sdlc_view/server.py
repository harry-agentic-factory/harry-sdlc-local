"""`sdlc-view view`: a local, read-only web page over the cross-project snapshot of `sdlc-view board`.

Standard library only (no web dependency). Binds to 127.0.0.1, serves:
    GET /            the page (sdlc_view/view.html), which polls /api/live
    GET /api/live    the JSON snapshot (optional ?project=<PREFIX>)
    GET /healthz     {"ok": true}

No port is hard-coded. Resolution order: --port, then SDLC_VIEW_PORT, then `"view": {"port": N}` at the
top level of the registry (~/.claude/sdlc/projects.json). None set → error.
"""
from __future__ import annotations

import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sdlc.config import registry_path

from .board import snapshot

HOST = "127.0.0.1"
PORT_ENV = "SDLC_VIEW_PORT"
# Only quoted in the error message: the next free port per the Brain port registry, which is
# where the real value has to be registered. Never used as a default.
SUGGESTED_PORT = 4002
PAGE = Path(__file__).with_name("view.html")


class PortNotConfigured(ValueError):
    pass


def _check_port(value, source: str) -> int:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"port invalide ({source}) : {value!r}") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"port hors plage 1-65535 ({source}) : {port}")
    return port


def resolve_port(cli_port: int | str | None = None) -> tuple[int, str]:
    """Return (port, source). Source is 'cli', 'env' or 'registry'."""
    if cli_port is not None:
        return _check_port(cli_port, "--port"), "cli"
    env = os.environ.get(PORT_ENV, "").strip()
    if env:
        return _check_port(env, PORT_ENV), "env"
    reg = registry_path()
    if reg.exists():
        try:
            data = json.loads(reg.read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"registre illisible ({reg}) : {e}") from None
        view = data.get("view") if isinstance(data, dict) else None
        if isinstance(view, dict) and view.get("port") is not None:
            return _check_port(view["port"], f"{reg} view.port"), "registry"
    raise PortNotConfigured(
        "aucun port configuré pour `sdlc-view view` : passe --port N, exporte "
        f"{PORT_ENV}=N, ou ajoute \"view\": {{\"port\": N}} au premier niveau de {reg}. "
        f"Port suggéré : {SUGGESTED_PORT} (prochain port libre du port-registry du Brain — "
        "à y enregistrer avant usage).")


class _Handler(BaseHTTPRequestHandler):
    server_version = "sdlc-view"

    def log_message(self, fmt, *args):  # noqa: D401 - keep stdout/stderr quiet
        pass

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        # DNS-rebinding guard: a foreign page resolving its own name to 127.0.0.1 must not be
        # able to read the board. Only loopback names are accepted in the Host header.
        host = (self.headers.get("Host") or "").strip().lower()
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        return name in ("127.0.0.1", "localhost", "[::1]")

    def do_GET(self):  # noqa: N802 - http.server API
        url = urlparse(self.path)
        if not self._host_ok():
            self._json(HTTPStatus.FORBIDDEN, {"error": "hôte non autorisé"})
        elif url.path in ("/", "/index.html"):
            self._send(HTTPStatus.OK, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/live":
            project = (parse_qs(url.query).get("project") or [None])[0]
            try:
                self._json(HTTPStatus.OK, snapshot(project))
            except KeyError as e:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(e.args[0]) if e.args else str(e)})
            except Exception as e:  # noqa: BLE001 - report instead of dropping the connection
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(e)})
        elif url.path == "/healthz":
            self._json(HTTPStatus.OK, {"ok": True})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "introuvable"})

    do_HEAD = do_GET

    def _read_only(self):
        self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "lecture seule"})

    do_POST = do_PUT = do_PATCH = do_DELETE = _read_only


def make_server(port: int, host: str = HOST) -> ThreadingHTTPServer:
    try:
        httpd = ThreadingHTTPServer((host, port), _Handler)
    except OSError as e:
        raise OSError(f"impossible d'écouter sur {host}:{port} : {e.strerror or e}") from None
    httpd.daemon_threads = True
    return httpd


def serve(cli_port: int | None = None) -> dict:
    """Blocking. Returns once interrupted (Ctrl-C)."""
    port, source = resolve_port(cli_port)
    httpd = make_server(port)
    url = f"http://{HOST}:{port}/"
    print(f"sdlc-view : {url} (port depuis {source}, Ctrl-C pour arrêter)", file=sys.stderr, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return {"url": url, "port": port, "portSource": source, "stopped": True}
