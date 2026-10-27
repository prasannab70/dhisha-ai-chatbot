"""Retell "Custom LLM" WebSocket: Retell handles speech; Disha's own agent (same prompt, tools and model
as the website and WhatsApp) decides every reply.

In Retell: create the agent with Response Engine = Custom LLM and set the WebSocket URL to
    wss://<your-host>/llm-websocket
Retell appends /{call_id} itself. No custom functions are needed in Retell: tools run inside run_turn.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from .. import agent, phone_line
from ..speech import fix_brand, speakable, spoken_digits
from ..config import settings
from ..db import Conversation, Handoff, Message, SessionLocal, Staff

log = logging.getLogger(__name__)
router = APIRouter(tags=["retell-llm"])

GREETING = "Hello, thank you for calling DhishaAI Complete Analytics. This is Disha. How can I help you today?"
RETRY = "Sorry, I didn't quite get that. Could you say it once more?"
BUSY = "Sorry, one moment please, I'm a little busy. Could you say that again in a few seconds?"
SETTLE_SECONDS = 0.6   # wait for the caller's sentence to settle; Retell re-sends it as the transcript grows
_THANKS = re.compile(r"^\W*(ok(ay)?\W*)?(thanks?|thank you|thank you (so|very) much|thanks a lot|thanks so much)\W*$", re.I)
# Caller is done: always ends the call
_BYE = re.compile(r"^\W*(ok(ay)?\W*)?((yes|yeah)\W*)?((thank you|thanks)( (so|very) much)?\W*)?"
                  r"(bye|bye bye|goodbye|good bye|see you|have a (nice|good|great) day|that'?s all|that is all|"
                  r"nothing else|no,? thanks?( you)?( so much)?|no,? that'?s (all|it)|i'?m (good|done|fine)|all good)\W*(bye|thank you|thanks)?\W*$", re.I)
# A plain "no" only means "I'm done" right after Disha asked "anything else?"
_NO_MORE = re.compile(r"^\W*(no|nope|nah|no no|not now|nothing|no,? nothing|no,? i'?m (good|fine|ok(ay)?)|that'?s it|no,? that'?s it|"
                      r"no,? (thank you|thanks)|no need|i'?m (good|fine|ok(ay)?))\W*$", re.I)
GOODBYE = "Thank you for calling DhishaAI Complete Analytics. Have a wonderful day!"
_ASKED_ELSE = re.compile(r"anything else", re.I)
HOLD = "Mm-hmm, go on."
# Said while a slow answer is being looked up, so the caller is not left in silence (rotates)
CHECKING = ["One moment, let me check that for you.", "Sure, give me a second while I check.",
            "Let me quickly look that up.", "Just a second, I'll check that for you."]
_NUMBER_TALK = re.compile(r"\b(number|phone|mobile|whats ?app|contact|call me)\b", re.I)
_FILLER = re.compile(r"\b(my|phone|mobile|whats ?app|number|is|it'?s|it is|the|and|okay|ok|so|uh|um|hmm|plus|that'?s)\b|[\s,.\-+:]", re.I)


def _partial_number(text: str) -> bool:
    """True when the caller has said only part of a phone number (fewer than 10 digits, nothing else)."""
    digits = "".join(re.findall(r"\d+", text))
    rest = _FILLER.sub("", re.sub(r"\d+", "", text))
    return 0 < len(digits) < 10 and not rest
_NOISE = re.compile(r"^\W*(\(.*\)|unintelligible|inaudible|\[.*\])\W*$", re.I)
FALLBACK = "Sorry, I'm having a little trouble on my side. Shall I ask a counsellor to call you back?"


def _turn(call_id: str, phone: str | None, text: str) -> tuple[str, str | None, bool]:
    """Runs one agent turn (blocking; called in a thread). Returns (reply, transfer_number, end_call)."""
    db = SessionLocal()
    try:
        conv_id = f"call:{call_id}"
        conv = agent.get_or_create_conversation(db, conv_id, "call", phone, "")
        was_muted = conv.muted
        reply = agent.run_turn(db, conv_id, text)
        db.refresh(conv)
        if conv.muted and not was_muted:  # handoff happened in this turn -> transfer the call
            h = db.scalars(select(Handoff).where(Handoff.conversation_id == conv_id, Handoff.staff_id.is_not(None))
                           .order_by(Handoff.id.desc())).first()
            staff = db.get(Staff, h.staff_id) if h else None
            if staff and staff.phone:
                number = "+" + "".join(ch for ch in staff.phone if ch.isdigit())
                return (reply or f"Connecting you to {staff.name} now, please hold."), number, False
        if reply is None:  # a human already owns this call
            return "", None, False
        return reply, None, False
    finally:
        db.close()


def _note_opening(call_id: str, phone: str, name: str, text: str) -> None:
    """Outgoing call: start the conversation with Disha's opening line so the model knows why she called."""
    db = SessionLocal()
    try:
        conv_id = f"call:{call_id}"
        conv = agent.get_or_create_conversation(db, conv_id, "call", phone, name)
        db.add(Message(conversation_id=conv.id, role="assistant", content=text))
        db.commit()
    finally:
        db.close()


def _small_talk(call_id: str, phone: str | None, text: str, asked_else: bool = False) -> tuple[str, bool] | None:
    """Answer 'thank you' / 'bye' / 'no, that's all' without the model (saves tokens and the rate limit).
    Returns (reply, end_call) or None. Skipped while a booking read-back is waiting for a yes/no."""
    done = bool(_BYE.match(text)) or (asked_else and bool(_NO_MORE.match(text)))
    thanks = bool(_THANKS.match(text))
    if not (done or thanks):
        return None
    db = SessionLocal()
    try:
        conv_id = f"call:{call_id}"
        conv = agent.get_or_create_conversation(db, conv_id, "call", phone, "")
        if conv.pending_booking or conv.muted:
            return None
        if thanks and asked_else:  # "thank you" in answer to "anything else?" also means they are done
            done = True
        reply = GOODBYE if done else "You're welcome! Is there anything else I can help you with?"
        db.add(Message(conversation_id=conv_id, role="user", content=text))
        db.add(Message(conversation_id=conv_id, role="assistant", content=reply))
        db.commit()
        return reply, done
    finally:
        db.close()


def _caller_said(transcript: list[dict]) -> str:
    """Everything the caller said since Disha last really spoke (they often speak in bursts, and pause inside
    a phone number; Disha's own 'Mm-hmm, go on' does not end the caller's turn)."""
    parts: list[str] = []
    for u in reversed(transcript or []):
        content = (u.get("content") or "").strip()
        if u.get("role") != "user":
            if content.startswith("Mm-hmm"):
                continue
            break
        parts.append(content)
    return " ".join(p for p in reversed(parts) if p).strip()


async def _send(ws: WebSocket, msg: dict) -> None:
    await ws.send_text(json.dumps(msg))


@router.websocket("/llm-websocket/{call_id}")
async def retell_llm(ws: WebSocket, call_id: str):
    await ws.accept()
    log.info("retell websocket connected: call %s", call_id)
    state = {"phone": None, "latest": -1}
    send_lock = asyncio.Lock()

    async def send(msg: dict) -> None:
        async with send_lock:
            await _send(ws, msg)

    turn_lock = asyncio.Lock()   # one model call at a time per call: protects the provider's rate limit

    async def answer(rid, text: str, number_mode: bool = False) -> None:
        """Runs the agent off the receive loop, so pings keep flowing while the model thinks."""
        await asyncio.sleep(SETTLE_SECONDS)
        if rid != state["latest"]:  # the caller kept talking; only the newest version gets an answer
            return
        async with turn_lock:
            if rid != state["latest"]:
                return
            try:
                if number_mode and _partial_number(text):  # caller paused inside the number: wait for the rest
                    quick = (HOLD, False)
                else:
                    quick = await asyncio.to_thread(_small_talk, call_id, state["phone"], text, state.get("asked_else", False))
                if quick:
                    reply, transfer, end = quick[0], None, quick[1]
                else:
                    job = asyncio.ensure_future(asyncio.to_thread(_turn, call_id, state["phone"], text))
                    wait = settings.call_checking_seconds
                    if wait > 0:
                        done, _ = await asyncio.wait({job}, timeout=wait)
                        if not done and rid == state["latest"]:
                            # slow answer (a lookup): "let me check" now, the answer follows on the same response
                            n = state.get("checks", 0)
                            state["checks"] = n + 1
                            await send({"response_type": "response", "response_id": rid,
                                        "content": CHECKING[n % len(CHECKING)] + " ", "content_complete": False,
                                        "end_call": False})
                            log.info("retell reply %s: (checking) %s", rid, CHECKING[n % len(CHECKING)])
                    reply, transfer, end = await job
                state["failures"] = 0
            except agent.RateLimited:
                log.warning("retell call %s: model rate limit", call_id)
                reply, transfer, end = BUSY, None, False
            except Exception:
                log.exception("retell turn failed for %s", call_id)
                state["failures"] = state.get("failures", 0) + 1
                # first failure: ask again (often a mishearing); only offer a callback if it keeps failing
                reply, transfer, end = (RETRY if state["failures"] < 2 else FALLBACK), None, False
        if rid != state["latest"]:  # caller already said something newer; Retell would drop this anyway
            return
        reply = speakable(reply)
        msg = {"response_type": "response", "response_id": rid, "content": reply,
               "content_complete": True, "end_call": end}
        if transfer:
            msg["transfer_number"] = transfer
        state["asked_else"] = bool(_ASKED_ELSE.search(reply or ""))
        state["asked_number"] = reply == HOLD or bool(_NUMBER_TALK.search(reply or ""))
        log.info("retell reply %s: %s", rid, (reply or "")[:80])
        await send(msg)

    await send({"response_type": "config", "config": {"auto_reconnect": True, "call_details": True}})
    from .phone import opening_line
    outbound = opening_line(call_id)
    first = GREETING
    if outbound:  # a call Disha placed (POST /phone/call): say who she is and why she is calling
        first, info = outbound
        state["phone"] = info["phone"]
        await asyncio.to_thread(_note_opening, call_id, info["phone"], info["name"], first)
    await send({"response_type": "response", "response_id": 0, "content": first,
                "content_complete": True, "end_call": False})
    tasks: set[asyncio.Task] = set()
    try:
        while True:
            data = json.loads(await ws.receive_text())
            kind = data.get("interaction_type")
            if kind == "ping_pong":
                await send({"response_type": "ping_pong", "timestamp": data.get("timestamp")})
            elif kind == "call_details":
                call = data.get("call", {}) or {}
                if call.get("direction") != "outbound":   # outgoing calls already know the number they dialled
                    state["phone"] = phone_line.caller(call.get("from_number"))
                log.info("retell call %s from %s on the %s line", call_id, state["phone"],
                         phone_line.line_for(call.get("to_number") if call.get("direction") != "outbound"
                                             else call.get("from_number")))
            elif kind == "reminder_required":
                await send({"response_type": "response", "response_id": data.get("response_id"),
                            "content": "Are you still there?", "content_complete": True, "end_call": False})
            elif kind == "response_required":
                rid = data.get("response_id")
                raw = _caller_said(data.get("transcript", []))
                number_mode = bool(state.get("asked_number") or _NUMBER_TALK.search(raw))
                text = spoken_digits(raw, 2 if number_mode else 6)
                # "this AI", "Dishay", "Nishai" ... -> DhishaAI, so company questions get company answers
                text = fix_brand(text, first_question=not state.get("caller_spoke"))
                if text.strip():
                    state["caller_spoke"] = True
                state["latest"] = rid
                log.info("retell heard %s: %s%s", rid, raw[:120], f"   ->   {text[:120]}" if text != raw else "")
                if not text:  # nothing said: let the caller keep talking
                    await send({"response_type": "response", "response_id": rid, "content": "",
                                "content_complete": True, "end_call": False})
                    continue
                if _NOISE.match(text):  # "(unintelligible audio)": no model call needed
                    await send({"response_type": "response", "response_id": rid, "content": RETRY,
                                "content_complete": True, "end_call": False})
                    continue
                t = asyncio.create_task(answer(rid, text, number_mode))
                tasks.add(t)
                t.add_done_callback(tasks.discard)
            # "update_only" carries live transcript only; nothing to do
    except WebSocketDisconnect:
        log.info("retell call %s ended", call_id)
    finally:
        for t in tasks:
            t.cancel()
