"""Meta WhatsApp Cloud API webhook: verification (GET) and inbound messages (POST)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from .. import agent, whatsapp
from ..config import settings
from ..db import SessionLocal, get_session

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])


@router.get("")
def verify(hub_mode: str = Query(alias="hub.mode", default=""),
           hub_token: str = Query(alias="hub.verify_token", default=""),
           hub_challenge: str = Query(alias="hub.challenge", default="")):
    if hub_mode == "subscribe" and hub_token == settings.wa_verify_token:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(403, "verification failed")


def handle_message(phone: str, name: str, text: str) -> None:
    """Runs in the background so Meta gets its 200 within seconds."""
    db: Session = SessionLocal()
    try:
        conv_id = f"wa:{phone}"
        agent.get_or_create_conversation(db, conv_id, "chat", "+91 " + phone[-10:][:5] + " " + phone[-5:] if len(phone) >= 10 else phone, name)
        reply = agent.run_turn(db, conv_id, text)
        if reply:
            whatsapp.send_text(db, phone, reply)
            db.commit()
        # reply None = a counsellor owns the thread; the console shows the message
    except Exception:
        log.exception("whatsapp turn failed for %s", phone)
        try:
            whatsapp.send_text(db, phone, "Sorry, something went wrong on my side. A counsellor will get back to you shortly.")
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("")
async def inbound(request: Request, bg: BackgroundTasks):
    body = await request.json()
    for m in whatsapp.parse_inbound(body):
        bg.add_task(handle_message, m["from"], m["name"], m["text"])
    return {"status": "ok"}
