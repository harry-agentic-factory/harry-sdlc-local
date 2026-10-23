"""Trello adapter. Credentials are read from the file named by the config, in-process only:
they never reach stdout, and error messages never carry a URL (it would contain the key)."""
from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CARD_FIELDS = "id,name,shortLink,shortUrl,idList,labels,dateLastActivity,closed,pos"
ATTACHMENT_FIELDS = "id,name,url,date,mimeType,bytes,isUpload"
RETRIES = 2
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class TrelloError(RuntimeError):
    pass


class TrelloSource:
    def __init__(self, config: dict):
        self.api = config.get("api", "https://api.trello.com/1").rstrip("/")
        self.board = config["board"]
        creds = json.loads(Path(config["credentials"]).expanduser().read_text())
        self._auth = {"key": creds["apikey"], "token": creds["token"]}
        self.lists = config.get("lists", {})

    def _request(self, method: str, url: str, label: str, headers: dict | None = None) -> bytes:
        req = urllib.request.Request(url, method=method, headers=headers or {})
        for attempt in range(RETRIES + 1):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                if e.code < 500 and e.code != 429 or attempt == RETRIES:
                    raise TrelloError(f"Trello {method} {label} -> HTTP {e.code}") from None
            except (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError) as e:
                # Trello drops idle keep-alive connections now and then: a dropped connection is retried.
                if attempt == RETRIES:
                    reason = getattr(e, "reason", None) or type(e).__name__
                    raise TrelloError(f"Trello {method} {label} -> {reason}") from None
            time.sleep(1 + attempt)
        raise TrelloError(f"Trello {method} {label} -> gave up")

    def _call(self, method: str, path: str, params: dict | None = None):
        query = urllib.parse.urlencode({**(params or {}), **self._auth})
        body = self._request(method, f"{self.api}{path}?{query}", path)
        return json.loads(body) if body else None

    def board_cards(self) -> list[dict]:
        return self._call("GET", f"/boards/{self.board}/cards/open", {"fields": CARD_FIELDS})

    def card(self, ref: str) -> dict:
        c = self._call("GET", f"/cards/{ref}", {
            "fields": "id,name,desc,shortLink,shortUrl,idList,labels,dateLastActivity,closed,pos,due",
            "actions": "commentCard", "attachments": "true", "attachment_fields": ATTACHMENT_FIELDS})
        names = {v: k for k, v in self.lists.items()}
        return {
            "id": c["id"], "shortLink": c["shortLink"], "url": c["shortUrl"], "name": c["name"],
            "list": names.get(c["idList"], c["idList"]), "pos": c.get("pos"), "due": c.get("due"),
            "labels": [lb.get("name") for lb in c.get("labels", [])],
            "dateLastActivity": c.get("dateLastActivity"), "closed": c.get("closed"),
            "desc": c.get("desc", ""),
            "comments": [{"date": a["date"], "by": a.get("memberCreator", {}).get("fullName"),
                          "text": a["data"]["text"]} for a in c.get("actions", [])],
            "attachments": [{k: a.get(k) for k in ("id", "name", "url", "date", "mimeType", "bytes", "isUpload")}
                            for a in c.get("attachments", [])],
        }

    def download(self, attachment: dict, dest_dir: Path) -> Path | None:
        """Save an uploaded attachment under dest_dir; a plain link attachment (isUpload=false) is skipped.
        Trello serves uploads only with an OAuth header — never with the key in the query string."""
        if not attachment.get("isUpload"):
            return None
        dest_dir.mkdir(parents=True, exist_ok=True)
        name = _UNSAFE.sub("_", attachment.get("name") or "attachment")
        path = dest_dir / f"{attachment['id']}-{name}"
        if path.exists() and (attachment.get("bytes") in (None, path.stat().st_size)):
            return path
        header = f'OAuth oauth_consumer_key="{self._auth["key"]}", oauth_token="{self._auth["token"]}"'
        path.write_bytes(self._request("GET", attachment["url"], f"attachment {attachment['id']}",
                                       {"Authorization": header}))
        return path

    def move(self, card_id: str, list_id: str) -> None:
        self._call("PUT", f"/cards/{card_id}", {"idList": list_id})

    def comment(self, card_id: str, text: str) -> None:
        self._call("POST", f"/cards/{card_id}/actions/comments", {"text": text})


def source_for(config: dict):
    kind = config.get("type")
    if kind == "trello":
        return TrelloSource(config)
    raise TrelloError(f"tracker type {kind!r} is not supported")
