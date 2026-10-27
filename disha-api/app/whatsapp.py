"""Meta WhatsApp Cloud API: send text, template, document, location; parse inbound webhook."""
from __future__ import annotations

import json
import logging

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .db import MessageLog

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v21.0"


def _post(payload: dict) -> dict:
    if not settings.wa_token:  # not configured: log only (local dev)
        log.info("WA (dry-run) %s", json.dumps(payload)[:300])
        return {"dry_run": True}
    r = httpx.post(
        f"{GRAPH}/{settings.wa_phone_number_id}/messages",
        headers={"Authorization": f"Bearer {settings.wa_token}"},
        json=payload,
        timeout=15,
    )
    if r.status_code >= 300:
        log.error("WA send failed %s %s", r.status_code, r.text[:300])
        raise RuntimeError(f"WhatsApp send failed: {r.status_code}")
    return r.json()


def _log(db: Session, to: str, kind: str, payload: dict, status: str = "sent") -> None:
    db.add(MessageLog(channel="whatsapp", to=to, kind=kind, payload=json.dumps(payload)[:4000], status=status))


def digits(phone: str) -> str:
    """Meta wants country code + number, digits only."""
    d = "".join(ch for ch in phone if ch.isdigit())
    return d if len(d) > 10 else "91" + d


def send_text(db: Session, to: str, text: str) -> None:
    payload = {"messaging_product": "whatsapp", "to": digits(to), "type": "text", "text": {"body": text}}
    _post(payload)
    _log(db, to, "text", payload)


def send_template(db: Session, to: str, name: str, params: list[str], lang: str = "en") -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": digits(to),
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": lang},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}],
        },
    }
    _post(payload)
    _log(db, to, f"template:{name}", payload)


def send_document(db: Session, to: str, url: str, filename: str, caption: str = "") -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": digits(to),
        "type": "document",
        "document": {"link": url, "filename": filename, "caption": caption},
    }
    _post(payload)
    _log(db, to, "document", payload)


def send_location(db: Session, to: str, lat: float, lng: float, name: str, address: str) -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": digits(to),
        "type": "location",
        "location": {"latitude": lat, "longitude": lng, "name": name, "address": address},
    }
    _post(payload)
    _log(db, to, "location", payload)


def parse_inbound(body: dict) -> list[dict]:
    """Return [{from, name, text, message_id}] for text messages in a webhook payload."""
    out = []
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c["wa_id"]: c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                if m.get("type") == "text":
                    out.append({
                        "from": m["from"],
                        "name": names.get(m["from"], ""),
                        "text": m["text"]["body"],
                        "message_id": m["id"],
                    })
                elif m.get("type") == "interactive":
                    i = m["interactive"]
                    text = (i.get("button_reply") or i.get("list_reply") or {}).get("title", "")
                    out.append({"from": m["from"], "name": names.get(m["from"], ""), "text": text, "message_id": m["id"]})
    return out
