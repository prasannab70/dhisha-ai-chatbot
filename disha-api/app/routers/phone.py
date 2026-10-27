"""Phone line switch (Plivo or Exotel) and outgoing calls through Retell.

GET  /phone/line            which line is active and which numbers are set
PUT  /phone/line            {"provider": "plivo" | "exotel"}  - switch the outgoing line (until restart)
POST /phone/call            {"to": "98765 43210", "name": "Kumar", "reason": "your demo class booking"}
                            Disha calls the person from the active line's number.
All need the console token (Authorization: Bearer <CONSOLE_TOKEN>).
"""
from __future__ import annotations

import logging
import time
from collections import deque

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import phone_line, tools
from .tools import require_token
from ..config import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/phone", tags=["phone"], dependencies=[Depends(require_token)])

# call_id -> what the outgoing call is about; read by the call websocket for the opening line
OUTBOUND: dict[str, dict] = {}
_recent: deque = deque()


@router.get("/line")
def get_line():
    return {"active": phone_line.active(),
            "numbers": {line: phone_line.number_of(line) or None for line in phone_line.LINES},
            "note": "Incoming calls work on every number attached to the Retell agent; "
                    "the active line is the one Disha calls out from."}


class LineIn(BaseModel):
    provider: str


@router.put("/line")
def set_line(inp: LineIn):
    p = inp.provider.lower().strip()
    if p not in phone_line.LINES:
        raise HTTPException(422, "provider must be plivo or exotel")
    if not phone_line.number_of(p):
        raise HTTPException(422, f"{p.upper()}_NUMBER is not set in .env")
    settings.phone_provider = p
    log.info("outgoing phone line switched to %s", p)
    return get_line()


class CallIn(BaseModel):
    to: str
    name: str | None = None
    reason: str | None = None     # e.g. "the callback you asked for", "your demo class tomorrow"


@router.post("/call")
def call(inp: CallIn):
    if not settings.retell_api_key:
        raise HTTPException(503, "RETELL_API_KEY is not set in .env")
    line = phone_line.active()
    if not line["number"]:
        raise HTTPException(503, f"No number for the active line ({line['provider']}): set "
                                 f"{line['provider'].upper()}_NUMBER in .env, or switch with PUT /phone/line")
    try:
        to = tools._norm_phone(inp.to)
    except tools.ToolError as e:
        raise HTTPException(422, str(e))
    now = time.time()
    while _recent and _recent[0] < now - 3600:
        _recent.popleft()
    if len(_recent) >= settings.outbound_calls_per_hour:
        raise HTTPException(429, "Outgoing call limit for this hour reached (OUTBOUND_CALLS_PER_HOUR)")
    body = {"from_number": line["number"], "to_number": phone_line.e164(to),
            "metadata": {"name": inp.name or "", "reason": inp.reason or "", "line": line["provider"]}}
    from .voice import agent_id
    if agent_id():
        body["override_agent_id"] = agent_id()
    try:
        r = httpx.post("https://api.retellai.com/v2/create-phone-call", json=body, timeout=15,
                       headers={"Authorization": f"Bearer {settings.retell_api_key}"})
    except Exception as e:
        raise HTTPException(502, f"Could not reach Retell ({type(e).__name__})")
    if r.status_code >= 300:
        detail = r.text[:300]
        if r.status_code in (401, 403):
            detail = "Retell rejected the API key (RETELL_API_KEY)."
        elif r.status_code == 404 or "from_number" in r.text:
            detail = (f"Retell does not know {line['number']} - import it under Phone Numbers (SIP trunking) and "
                      f"attach the agent for outbound calls. Retell said: {r.text[:200]}")
        raise HTTPException(502, detail)
    _recent.append(now)
    call_id = r.json().get("call_id", "")
    OUTBOUND[call_id] = {"name": inp.name or "", "reason": inp.reason or "", "phone": to}
    log.info("outgoing call %s to %s via %s (%s)", call_id, to, line["provider"], line["number"])
    return {"call_id": call_id, "from": line["number"], "line": line["provider"], "to": to}


def opening_line(call_id: str) -> tuple[str, dict] | None:
    """Disha's first words on a call she placed (instead of the 'thanks for calling' greeting)."""
    info = OUTBOUND.pop(call_id, None)
    if info is None:
        return None
    hi = f"Hello {info['name']}, " if info["name"] else "Hello, "
    about = f" I'm calling about {info['reason']}." if info["reason"] else ""
    return f"{hi}this is Disha from DhishaAI Complete Analytics.{about} Is this a good time to talk?", info
