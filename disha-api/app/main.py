"""Disha receptionist API.

    uvicorn app.main:app --reload

Endpoints
  POST /chat                      local test of the agent without WhatsApp (same loop)
  /tools/*                        the nine tools over HTTP (Bearer CONSOLE_TOKEN)
  GET|POST /webhooks/whatsapp     Meta Cloud API verification and inbound messages
  POST /webhooks/retell/{tool}    Retell custom functions
  /console/*                      receptionist screen data and actions
  GET /health
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import agent, scheduler
from .db import get_session, init_db
from .routers import console, phone, retell, retell_llm, tools, voice, whatsapp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    _seed_if_empty()
    _use_website_courses()
    scheduler.start()
    yield
    scheduler.scheduler.shutdown(wait=False)


def _seed_if_empty() -> None:
    """A brand-new database gets the starter courses, counsellors and demo slots (edit them in the database or through the admin portal later)."""
    from sqlalchemy import select
    from .db import Course, SessionLocal
    db = SessionLocal()
    try:
        empty = db.scalar(select(Course)) is None
    finally:
        db.close()
    if empty:
        from .seed import seed
        seed()


def _use_website_courses() -> None:
    """Courses come from dhishaai.com (app/knowledge.py) unless WordPress sync is configured."""
    from .config import settings as cfg
    from .db import SessionLocal
    from .knowledge import apply_website_courses
    if cfg.wp_base_url:
        return
    db = SessionLocal()
    try:
        apply_website_courses(db)
    except Exception:
        logging.getLogger("startup").exception("could not apply website courses")
    finally:
        db.close()


app = FastAPI(title="Disha Front Desk API", version="0.1.0", lifespan=lifespan)
from .config import settings as _settings
_origins = [o.strip() for o in _settings.allowed_origins.split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(tools.router)
app.include_router(whatsapp.router)
app.include_router(retell.router)
app.include_router(retell_llm.router)
app.include_router(voice.router)
app.include_router(phone.router)

# "Talk to Disha AI" page: http://localhost:8000/disha/
from pathlib import Path as _Path
from fastapi.staticfiles import StaticFiles as _StaticFiles
_voice_dir = _Path(__file__).resolve().parent.parent / "static" / "disha-voice"
if _voice_dir.is_dir():
    app.mount("/disha", _StaticFiles(directory=str(_voice_dir), html=True), name="disha-voice")
# Test chat page for checking the chat end to end before the website front end exists: http://localhost:8000/test-chat/
_test_dir = _Path(__file__).resolve().parent.parent / "static" / "test-chat"
if _test_dir.is_dir():
    app.mount("/test-chat", _StaticFiles(directory=str(_test_dir), html=True), name="test-chat")
app.include_router(console.router)


@app.get("/")
def root():
    return {"service": "Disha API", "docs": "/docs", "health": "/health", "voice_page": "/disha/", "test_chat": "/test-chat/",
            "website_chat": "POST /web/chat (X-Site-Key)", "data": "/console/* (Bearer CONSOLE_TOKEN; /console/tables/{name}/csv)",
            "whatsapp_webhook": "/webhooks/whatsapp", "retell_llm": "wss://<host>/llm-websocket"}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/agent/check")
def agent_check():
    """One tiny model call per provider in use, so the setup can be verified from the demo page or curl."""
    from .config import settings
    if settings.llm_mode.lower() == "hybrid":
        out = {"ok": True, "mode": "hybrid"}
        for role in ("basic", "complex"):
            p = getattr(settings, f"hybrid_{role}_provider").lower()
            info = agent.provider_info(p)
            try:
                out[role] = {"provider": p, "model": info["model"], "reply": agent.ping_model(p)}
            except Exception as e:
                raise HTTPException(502, f"hybrid {role} [{p} / {info['model']}] model call failed ({type(e).__name__}): {str(e)[:300]}")
        return out
    info = agent.provider_info()
    try:
        reply = agent.ping_model()
        return {"ok": True, "mode": "single", "provider": info["provider"], "model": info["model"], "reply": reply}
    except Exception as e:
        raise HTTPException(502, f"[{info['provider']} / {info['model']}] Model call failed ({type(e).__name__}): {str(e)[:300]}")


@app.get("/agent/providers")
def agent_providers():
    """Which providers are usable right now (key present or no key needed), and which mode/provider is active."""
    from .config import settings
    rows = [
        {"provider": "groq", "model": settings.groq_model, "ready": bool(settings.groq_api_key), "note": "free tier"},
        {"provider": "ollama", "model": settings.ollama_model, "ready": True, "note": "local, needs `ollama serve`"},
        {"provider": "anthropic", "model": settings.anthropic_model, "ready": bool(settings.anthropic_api_key), "note": "paid"},
        {"provider": "openai", "model": settings.openai_model, "ready": bool(settings.openai_api_key), "note": "paid"},
    ]
    hybrid = {"basic": settings.hybrid_basic_provider.lower(), "complex": settings.hybrid_complex_provider.lower()}
    mode = settings.llm_mode.lower()
    return {"mode": mode, "active": "hybrid" if mode == "hybrid" else settings.llm_provider.lower(),
            "hybrid": hybrid, "providers": rows}


class ProviderIn(BaseModel):
    provider: str                 # groq | ollama | anthropic | openai | hybrid
    model: str | None = None      # single mode: optional model name for that provider
    basic: str | None = None      # hybrid mode: provider for simple questions
    complex: str | None = None    # hybrid mode: provider for complex questions


@app.put("/agent/provider", dependencies=[Depends(tools.require_token)])
def set_provider(inp: ProviderIn):
    """Switch provider or mode at runtime (until restart; put it in .env to make it permanent)."""
    from .config import settings
    p = inp.provider.lower()
    before = (settings.llm_mode, settings.llm_provider, settings.hybrid_basic_provider, settings.hybrid_complex_provider)
    if p == "hybrid":
        basic, complex_ = (inp.basic or settings.hybrid_basic_provider).lower(), (inp.complex or settings.hybrid_complex_provider).lower()
        if basic not in agent.PROVIDERS or complex_ not in agent.PROVIDERS:
            raise HTTPException(422, f"basic and complex must each be one of {', '.join(agent.PROVIDERS)}")
        settings.llm_mode, settings.hybrid_basic_provider, settings.hybrid_complex_provider = "hybrid", basic, complex_
        try:
            return agent_check()
        except HTTPException as e:
            settings.llm_mode, settings.llm_provider, settings.hybrid_basic_provider, settings.hybrid_complex_provider = before
            raise HTTPException(502, f"not switched: {e.detail}")
    if p not in agent.PROVIDERS:
        raise HTTPException(422, "provider must be groq, ollama, anthropic, openai or hybrid")
    prev_model = getattr(settings, f"{p}_model")
    settings.llm_mode, settings.llm_provider = "single", p
    if inp.model:
        setattr(settings, f"{p}_model", inp.model.strip())
    info = agent.provider_info()
    try:
        reply = agent.ping_model()
        return {"ok": True, "mode": "single", "provider": info["provider"], "model": info["model"], "reply": reply}
    except Exception as e:
        settings.llm_mode, settings.llm_provider, settings.hybrid_basic_provider, settings.hybrid_complex_provider = before
        setattr(settings, f"{p}_model", prev_model)
        raise HTTPException(502, f"[{info['provider']} / {info['model']}] not switched: model call failed ({type(e).__name__}): {str(e)[:200]}")


# ---- Website channel (called by the WordPress plugin's server-side proxy, never by the browser directly) ----
import time as _time
from collections import defaultdict, deque
from fastapi import Header, Request

_hits: dict[str, deque] = defaultdict(deque)


def _rate_limited(key: str) -> bool:
    now = _time.time(); q = _hits[key]
    while q and q[0] < now - 60:
        q.popleft()
    if len(q) >= _settings.web_rate_limit_per_minute:
        return True
    q.append(now); return False


class WebChatIn(BaseModel):
    visitor_id: str
    text: str
    name: str | None = None
    phone: str | None = None


@app.post("/web/chat")
def web_chat(inp: WebChatIn, request: Request, db: Session = Depends(get_session), x_site_key: str = Header(default="")):
    if x_site_key != _settings.site_key:
        raise HTTPException(401, "bad site key")
    vid = "".join(ch for ch in inp.visitor_id if ch.isalnum() or ch in "-_")[:40]
    if not vid or not inp.text.strip():
        raise HTTPException(422, "visitor_id and text are required")
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    if _rate_limited(ip) or _rate_limited("v:" + vid):
        raise HTTPException(429, "too many messages; please wait a minute")
    conv_id = f"web:{vid}"
    agent.get_or_create_conversation(db, conv_id, "chat", inp.phone, inp.name or "")
    try:
        reply = agent.run_turn(db, conv_id, inp.text.strip()[:2000])
    except Exception as e:
        logging.getLogger("web").exception("agent failed")
        raise HTTPException(502, f"Agent failed ({type(e).__name__})")
    from sqlalchemy import func
    from .db import Message
    last_id = db.scalar(select(func.max(Message.id)).where(Message.conversation_id == conv_id,
                                                           Message.role.in_(("assistant", "human")))) or 0
    return {"reply": reply, "muted": reply is None, "conversation_id": conv_id, "last_id": last_id}


@app.get("/web/messages")
def web_messages(visitor_id: str, after: int = 0, db: Session = Depends(get_session), x_site_key: str = Header(default="")):
    """Counsellor replies the website visitor has not seen yet (the widget polls this after a handoff)."""
    if x_site_key != _settings.site_key:
        raise HTTPException(401, "bad site key")
    from .db import Conversation, Message
    vid = "".join(ch for ch in visitor_id if ch.isalnum() or ch in "-_")[:40]
    conv_id = f"web:{vid}"
    conv = db.get(Conversation, conv_id)
    if not conv:
        return {"messages": [], "muted": False, "last_id": after}
    rows = db.scalars(select(Message).where(Message.conversation_id == conv_id, Message.id > after,
                                            Message.role.in_(("human", "assistant"))).order_by(Message.id)).all()
    return {"messages": [{"id": m.id, "from": "counsellor" if m.role == "human" else "disha", "text": m.content} for m in rows],
            "muted": bool(conv.muted), "last_id": rows[-1].id if rows else after}


@app.post("/admin/refresh-website", dependencies=[Depends(tools.require_token)])
def refresh_website_now():
    """Re-read dhishaai.com now (the same job also runs every night)."""
    from . import site_refresh
    return site_refresh.refresh()


@app.get("/admin/website-status")
def website_status():
    """When the website knowledge was last refreshed, and what it holds."""
    from . import site_refresh
    from .config import settings as cfg
    data = site_refresh.load()
    return {"enabled": cfg.website_refresh_enabled, "every_hours": cfg.website_refresh_hours, "website": cfg.website_url,
            "refreshed_at": data.get("refreshed_at"), "using": "live website copy" if data.get("pages") else "nothing yet (refresh pending or failed)",
            "pages": [{"name": p["name"], "url": p["url"], "sections": len(p["chunks"]), "fetched_at": p.get("fetched_at")} for p in data.get("pages", [])],
            "course_updates": data.get("course_updates", {})}


@app.get("/admin/lms-status", dependencies=[Depends(tools.require_token)])
def lms_status():
    """What has reached the DhishaAI Admin Portal, what is waiting, and the last error."""
    from . import lms
    return lms.status()


@app.post("/admin/lms-check", dependencies=[Depends(tools.require_token)])
def lms_check():
    """Sign in to the admin portal once, to prove the address and account work."""
    from . import lms
    try:
        return lms.check()
    except Exception as e:
        raise HTTPException(502, str(e)[:300])


@app.post("/admin/lms-retry", dependencies=[Depends(tools.require_token)])
def lms_retry():
    """Queue every failed portal sync again and send now."""
    from . import lms
    n = lms.retry_failed()
    return {"requeued": n, **lms.flush()}


@app.post("/admin/sync-courses", dependencies=[Depends(tools.require_token)])
def sync_courses_now():
    from . import wp_sync
    if not _settings.wp_base_url:
        raise HTTPException(422, "WP_BASE_URL is not set")
    return {"synced": wp_sync.sync_courses()}


class ChatIn(BaseModel):
    conversation_id: str
    text: str
    channel: str = "chat"
    phone: str | None = None
    name: str = ""


@app.post("/chat")
def chat(inp: ChatIn, db: Session = Depends(get_session)):
    """Talk to Disha directly (for local testing and the demo page)."""
    agent.get_or_create_conversation(db, inp.conversation_id, inp.channel, inp.phone, inp.name)
    try:
        reply = agent.run_turn(db, inp.conversation_id, inp.text)
    except Exception as e:
        logging.getLogger("chat").exception("agent failed")
        raise HTTPException(502, f"Agent failed ({type(e).__name__}): {str(e)[:300]}")
    return {"reply": reply, "muted": reply is None}
