"""Talk-to-Disha web page: starts a Retell web call for the browser.

The page (static/disha-voice/, served at /disha/) asks POST /voice/web-call for a one-time access token.
This backend calls Retell's create-web-call API with RETELL_API_KEY (which never reaches the browser) and
RETELL_AGENT_ID (the agent id, or the agent's share link - the id is read from it).
"""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict, deque

import httpx
from fastapi import APIRouter, HTTPException, Request

from ..config import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])
_hits: dict[str, deque] = defaultdict(deque)


def agent_id() -> str:
    """RETELL_AGENT_ID may be the bare id or any Retell link that contains it (e.g. the orb share link)."""
    m = re.search(r"agent_[A-Za-z0-9]+", settings.retell_agent_id or "")
    return m.group(0) if m else ""


def _limited(ip: str) -> bool:
    now, q = time.time(), _hits[ip]
    while q and q[0] < now - 60:
        q.popleft()
    if len(q) >= settings.voice_calls_per_minute:
        return True
    q.append(now)
    return False


@router.get("/config")
def voice_config():
    """What the page needs to know before starting (no secrets)."""
    return {"ready": bool(settings.retell_api_key and agent_id()), "agent_id": agent_id() or None}


@router.post("/web-call")
def create_web_call(request: Request):
    if not settings.retell_api_key or not agent_id():
        raise HTTPException(503, "Voice is not set up yet: put RETELL_API_KEY and RETELL_AGENT_ID (the agent link or id) in .env and restart.")
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    if _limited(ip):
        raise HTTPException(429, "Too many calls started from this device; please wait a minute.")
    try:
        r = httpx.post("https://api.retellai.com/v2/create-web-call",
                       headers={"Authorization": f"Bearer {settings.retell_api_key}", "Content-Type": "application/json"},
                       json={"agent_id": agent_id()}, timeout=15)
    except Exception as e:
        log.exception("retell create-web-call failed")
        raise HTTPException(502, f"Could not reach Retell ({type(e).__name__})")
    if r.status_code >= 300:
        detail = r.text[:200]
        if r.status_code in (401, 403):
            detail = "Retell rejected the API key: check RETELL_API_KEY in .env (Retell dashboard -> API Keys)."
        elif r.status_code == 404:
            detail = "Retell could not find that agent: check RETELL_AGENT_ID in .env."
        raise HTTPException(502, detail)
    data = r.json()
    return {"access_token": data.get("access_token"), "call_id": data.get("call_id")}
