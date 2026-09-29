"""Trello adapter. Credentials are read from the file named by the config, in-process only:
they never reach stdout, and error messages never carry a URL (it would contain the key)."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CARD_FIELDS = "id,name,shortLink,shortUrl,idList,labels,dateLastActivity,closed"


class TrelloError(RuntimeError):
    pass


class TrelloSource:
    def __init__(self, config: dict):
        self.api = config.get("api", "https://api.trello.com/1").rstrip("/")
        self.board = config["board"]
        creds = json.loads(Path(config["credentials"]).expanduser().read_text())
        self._auth = {"key": creds["apikey"], "token": creds["token"]}
        self.lists = config.get("lists", {})

    def _call(self, method: str, path: str, params: dict | None = None):
        query = urllib.parse.urlencode({**(params or {}), **self._auth})
        req = urllib.request.Request(f"{self.api}{path}?{query}", method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            raise TrelloError(f"Trello {method} {path} -> HTTP {e.code}") from None
        except urllib.error.URLError as e:
            raise TrelloError(f"Trello {method} {path} -> {e.reason}") from None
        return json.loads(body) if body else None

    def board_cards(self) -> list[dict]:
        return self._call("GET", f"/boards/{self.board}/cards/open", {"fields": CARD_FIELDS})

    def card(self, ref: str) -> dict:
        c = self._call("GET", f"/cards/{ref}", {
            "fields": "id,name,desc,shortLink,shortUrl,idList,labels,dateLastActivity,closed",
            "actions": "commentCard", "attachments": "true", "attachment_fields": "name,url,date"})
        names = {v: k for k, v in self.lists.items()}
        return {
            "id": c["id"], "shortLink": c["shortLink"], "url": c["shortUrl"], "name": c["name"],
            "list": names.get(c["idList"], c["idList"]),
            "labels": [lb.get("name") for lb in c.get("labels", [])],
            "dateLastActivity": c.get("dateLastActivity"), "closed": c.get("closed"),
            "desc": c.get("desc", ""),
            "comments": [{"date": a["date"], "by": a.get("memberCreator", {}).get("fullName"),
                          "text": a["data"]["text"]} for a in c.get("actions", [])],
            "attachments": c.get("attachments", []),
        }

    def move(self, card_id: str, list_id: str) -> None:
        self._call("PUT", f"/cards/{card_id}", {"idList": list_id})

    def comment(self, card_id: str, text: str) -> None:
        self._call("POST", f"/cards/{card_id}/actions/comments", {"text": text})


def source_for(config: dict):
    kind = config.get("type")
    if kind == "trello":
        return TrelloSource(config)
    raise TrelloError(f"tracker type {kind!r} is not supported")
