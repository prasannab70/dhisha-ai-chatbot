"""The agent: a plain tool-calling loop over the Anthropic Messages API.

    reply = run_turn(db, conversation_id, user_text)

Keeps the last 40 messages of the conversation in the database, rebuilds the system
prompt each turn, dispatches tool calls to app.tools, and returns the final text.
"""
from __future__ import annotations

import contextvars
import json
import time
import logging
import re
from datetime import datetime

import anthropic
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import tools
from .config import settings
from .db import Conversation, Message
from .prompt import TOOL_DEFS, build_system_prompt
from .schemas import (
    BookIn, BrochureIn, CallbackIn, CoursesIn, DirectionsIn, HandoffIn, SlotsIn, ToolContext,
)

log = logging.getLogger(__name__)
MAX_ROUNDS = 8
HISTORY = 40

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


# ---- Provider layer: Anthropic natively; Groq / Ollama / OpenAI through the OpenAI-compatible chat API ----

PROVIDERS = ("groq", "ollama", "anthropic", "openai")
_provider_now: contextvars.ContextVar[str | None] = contextvars.ContextVar("provider_now", default=None)


def provider_info(provider: str | None = None) -> dict:
    """Connection details for a provider: the one given, the one this turn is running on, or LLM_PROVIDER."""
    p = (provider or _provider_now.get() or settings.llm_provider).lower()
    if p == "groq":
        return {"provider": "groq", "model": settings.groq_model, "base_url": settings.groq_base_url, "key": settings.groq_api_key, "needs_key": True}
    if p == "ollama":
        return {"provider": "ollama", "model": settings.ollama_model, "base_url": settings.ollama_base_url, "key": "ollama", "needs_key": False}
    if p == "openai":
        return {"provider": "openai", "model": settings.openai_model, "base_url": settings.openai_base_url, "key": settings.openai_api_key, "needs_key": True}
    return {"provider": "anthropic", "model": settings.anthropic_model, "base_url": "", "key": settings.anthropic_api_key, "needs_key": True}


# ---- Hybrid routing: cheap model for simple questions, strong model for complex ones (no extra model call) ----
_COMPLEX = re.compile(
    r"\b(book|booking|schedule|slot|appointment|demo|counsel+ing|counsel+or|reschedul\w*|cancel\w*|suit|suits|recommend\w*|"
    r"which course|best course|right course|career|switch|confus\w*|compare|difference|better|direction\w*|route|reach|"
    r"coming from|bus|metro|bike|car|drive|talk to|speak to|human|person|someone|call me|call back|callback|complain\w*|"
    r"refund|discount|placement|emi|instal+ment|scholarship|problem|issue|not happy)\b", re.I)
_STICKY_TURNS = 4                       # once a conversation turns complex, stay on the strong model for a few turns
_sticky: dict[str, int] = {}


def route(conv: Conversation, text: str) -> tuple[str, str]:
    """Which provider answers this message, and why. Single mode always returns LLM_PROVIDER."""
    if settings.llm_mode.lower() != "hybrid":
        return settings.llm_provider.lower(), "single mode"
    basic, complex_ = settings.hybrid_basic_provider.lower(), settings.hybrid_complex_provider.lower()
    reason = ""
    if conv.booking_type or conv.pending_booking:
        reason = "booking in progress"
    elif _COMPLEX.search(text or ""):
        reason = f"complex topic ('{_COMPLEX.search(text).group(0)}')"
    elif len(text or "") > 160 or (text or "").count("?") >= 2:
        reason = "long or multi-part message"
    elif _sticky.get(conv.id, 0) > 0:
        _sticky[conv.id] -= 1
        return complex_, "continuing a complex conversation"
    if reason:
        _sticky[conv.id] = _STICKY_TURNS
        return complex_, reason
    return basic, "simple question"


def _openai_tools() -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in TOOL_DEFS]


class ToolCallParseError(RuntimeError):
    """The model emitted a malformed tool call (Groq returns 400 tool_use_failed). Retryable."""


def _timeout(provider: str) -> int:
    from .config import settings
    return settings.ollama_timeout_seconds if provider == "ollama" else settings.llm_timeout_seconds


class RateLimited(RuntimeError):
    """The provider's per-minute token/request limit was hit and waiting did not help."""


def _retry_after(r: httpx.Response) -> float:
    m = re.search(r"try again in ([\d.]+)(ms|s)", r.text)
    if m:
        return float(m.group(1)) / (1000 if m.group(2) == "ms" else 1)
    try:
        return float(r.headers.get("retry-after", "5"))
    except ValueError:
        return 5.0


def chat_completion(messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 500, tool_choice: str = "auto") -> dict:
    """One OpenAI-compatible call (Groq, Ollama, OpenAI). Returns the assistant message dict.
    On a rate limit (429): wait if the provider asks for a short pause, else fall back to GROQ_FALLBACK_MODEL."""
    info = provider_info()
    models = [info["model"]]
    if info["provider"] == "groq" and settings.groq_fallback_model and settings.groq_fallback_model != info["model"]:
        models.append(settings.groq_fallback_model)
    r = limited = None
    for model in models:
        # temperature 0: the same question gets the same answer every time, whoever asks
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice
        for _ in range(2):
            r = httpx.post(f"{info['base_url'].rstrip('/')}/chat/completions",
                           headers={"content-type": "application/json", "authorization": f"Bearer {info['key'] or 'none'}"},
                           json=body, timeout=_timeout(info["provider"]))
            if r.status_code != 429:
                break
            wait = _retry_after(r)
            if wait > settings.llm_max_rate_wait_seconds:
                break
            log.warning("%s rate limit on %s; waiting %.1fs", info["provider"], model, wait)
            time.sleep(wait + 0.2)
        if r.status_code != 429:
            if model != models[0] and r.status_code in (400, 404) and "model" in r.text.lower():
                # the fallback model is not available on this account: report the rate limit, not a crash
                log.warning("fallback model %s is not available (%s); set GROQ_FALLBACK_MODEL to a model your "
                            "Groq account has, or leave it empty", model, r.status_code)
                r = limited
            break
        limited = r
        log.warning("%s rate limit on %s; trying the next model", info["provider"], model)
    if r.status_code == 429:
        raise RateLimited(f"{info['provider']} rate limit: {r.text[:200]}")
    if r.status_code == 400 and "tool_use_failed" in r.text:
        raise ToolCallParseError(r.text[:300])
    if r.status_code >= 300:
        raise RuntimeError(f"{info['provider']} {r.status_code}: {r.text[:300]}")
    msg = r.json()["choices"][0]["message"]
    # Some models return tool_calls with None/"" arguments; normalise
    for c in msg.get("tool_calls") or []:
        fn = c.setdefault("function", {})
        if not fn.get("arguments"):
            fn["arguments"] = "{}"
    return msg


def ping_model(provider: str | None = None) -> str:
    """Tiny call used by /agent/check. Returns the reply text or raises."""
    token = _provider_now.set(provider) if provider else None
    try:
        return _ping()
    finally:
        if token:
            _provider_now.reset(token)


def _ping() -> str:
    info = provider_info()
    if info["needs_key"] and not info["key"]:
        raise RuntimeError(f"{info['provider'].upper()}_API_KEY is empty in .env")
    if info["provider"] == "anthropic":
        res = client().messages.create(model=info["model"], max_tokens=10, messages=[{"role": "user", "content": "Reply with the single word OK"}])
        return "".join(b.text for b in res.content if b.type == "text")
    m = chat_completion([{"role": "user", "content": "Reply with the single word OK"}], max_tokens=10)
    return (m.get("content") or "").strip()


def dispatch(db: Session, name: str, args: dict, ctx: ToolContext) -> dict | list:
    """Map a tool call from the model to the typed function. Raises ToolError for caller-facing problems."""
    if name == "save_caller":
        out = tools.save_caller(db, args.get("name"), args.get("phone"), ctx)
        ctx.caller_name, ctx.caller_phone = out["caller_name"], out["caller_phone"]
        return out
    if name == "get_courses":
        return tools.get_courses(db, CoursesIn(**args))
    if name == "get_company_info":
        from .knowledge import get_company_info
        return get_company_info(str(args.get("topic") or ""))
    if name == "get_available_staff":
        return tools.get_available_staff(db)
    if name == "get_slots":
        return tools.get_slots(db, SlotsIn(**args), ctx)
    if name == "book_slot":
        key = f"{ctx.conversation_id}:{args.get('date')}:{args.get('time')}:{args.get('type')}"
        return tools.book_slot(db, BookIn(**args, idempotency_key=key), ctx)
    if name == "send_brochure":
        return tools.send_brochure(db, BrochureIn(**args), ctx)
    if name == "get_office_address":
        return tools.get_office_address(db, ctx)
    if name == "get_directions":
        return tools.get_directions(db, DirectionsIn(**args))
    if name == "handoff":
        return tools.handoff(db, HandoffIn(**args), ctx)
    if name == "create_callback":
        return tools.create_callback(db, CallbackIn(**args), ctx)
    raise tools.ToolError(f"Unknown tool {name}")


def _capture_identity(conv: Conversation, text: str) -> None:
    """Cheap pre-pass so the prompt knows name/number even before the model confirms them."""
    if not conv.caller_name:
        m = re.search(r"\b(?:i am|i'm|this is|my name is|name is)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", text, re.I)
        if m:
            conv.caller_name = m.group(1).title()
    if not conv.phone or conv.phone.startswith("unknown"):
        m = re.search(r"(?:\+?91)?([6-9]\d{9})\b", re.sub(r"[\s-]", "", text))
        if m:
            conv.phone = "+91 " + m.group(1)[:5] + " " + m.group(1)[5:]


def get_or_create_conversation(db: Session, conversation_id: str, channel: str, phone: str | None, name: str = "") -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if not conv:
        conv = Conversation(id=conversation_id, phone=phone or "unknown", channel=channel, caller_name=name or "")
        db.add(conv)
        db.commit()
    return conv


def history(db: Session, conversation_id: str) -> list[dict]:
    rows = db.scalars(select(Message).where(Message.conversation_id == conversation_id)
                      .order_by(Message.id.desc()).limit(HISTORY)).all()
    out = []
    for m in reversed(rows):
        if m.role == "user":
            out.append({"role": "user", "content": m.content})
        elif m.role == "assistant":
            out.append({"role": "assistant", "content": m.content})
        elif m.role == "human":  # a counsellor's reply, shown to the model as context
            out.append({"role": "assistant", "content": f"[Counsellor]: {m.content}"})
    # Anthropic needs the first message to be a user turn
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


OFF_TOPIC_REPLY = ("Sorry, I can only help with questions about DhishaAI: our courses, services, products, team, "
                   "careers and counselling. What would you like to know?")
# Obvious off-topic questions answered without the model: arithmetic like "what is 1+1", "25 x 4", "calculate 10/2"
_ARITHMETIC = re.compile(r"^\W*(what\s*(is|'s)|whats|calculate|solve|tell me)?\s*\(?\s*-?\d+(\.\d+)?\s*"
                         r"([-+*/x×÷^%]|plus|minus|times|into|divided by|multiplied by)\s*\(?\s*-?\d+(\.\d+)?\)?"
                         r"(\s*([-+*/x×÷^%]|plus|minus|times|into|divided by|multiplied by)\s*-?\d+(\.\d+)?)*\s*\??\W*$", re.I)


_NOT_ON_SITE = re.compile(r"(isn't|is not|not|doesn't|does not)\s+(mentioned|listed|available|have that|mention)[^.]*\b(website|site)\b"
                          r"|\b(website|site)\s+(doesn't|does not)\s+(mention|say|list)", re.I)


def is_off_topic_math(text: str) -> bool:
    if re.search(r"\d{5,}", text or ""):  # phone numbers like 98765-43210 are not sums
        return False
    return bool(_ARITHMETIC.match(text or ""))


def _anthropic_create(**kw):
    """messages.create at temperature 0. Older SDKs take temperature= directly; newer ones only through extra_body,
    and some newer models refuse it altogether - then the call is made without it rather than failing."""
    import inspect
    try:
        if "temperature" in inspect.signature(client().messages.create).parameters:
            return client().messages.create(temperature=0, **kw)
        return client().messages.create(extra_body={"temperature": 0}, **kw)
    except Exception as e:
        if "temperature" not in str(e).lower():
            raise
        log.warning("model does not accept temperature; calling without it")
        return client().messages.create(**kw)


def _run_model(provider: str, system: str, messages: list[dict], run_tool) -> str:
    """One full tool-calling loop on the given provider. Returns the final reply text."""
    token = _provider_now.set(provider)
    try:
        final_text = ""
        if provider_info()["provider"] == "anthropic":
            for _ in range(MAX_ROUNDS):
                res = _anthropic_create(model=provider_info()["model"], max_tokens=500, system=system,
                                        tools=TOOL_DEFS, messages=messages)
                messages.append({"role": "assistant", "content": [b.model_dump() for b in res.content]})
                if res.stop_reason != "tool_use":
                    final_text = "".join(b.text for b in res.content if b.type == "text").strip()
                    break
                results = [{"type": "tool_result", "tool_use_id": b.id, "content": run_tool(b.name, b.input)}
                           for b in res.content if b.type == "tool_use"]
                messages.append({"role": "user", "content": results})
            else:
                final_text = "Sorry, I could not complete that. Shall I connect you to a counsellor?"
        else:  # Groq / Ollama / OpenAI: OpenAI-compatible tool calling
            oa_messages = [{"role": "system", "content": system}, *messages]
            oa_tools = _openai_tools()
            for _ in range(MAX_ROUNDS):
                m = None
                for attempt in range(3):
                    try:
                        # last attempt: no tools at all, so the model can only answer in words (Groq can still
                        # reject tool_choice="none" when the model insists on a tool call)
                        m = chat_completion(oa_messages, oa_tools if attempt < 2 else None)
                        break
                    except ToolCallParseError as e:
                        log.warning("malformed tool call from %s (attempt %d): %s", provider_info()["provider"], attempt + 1, e)
                if m is None:
                    raise RuntimeError("model kept producing malformed tool calls")
                # strip None values the model may pass (e.g. save_caller with name=null, phone=null)
                calls = m.get("tool_calls") or []
                cleaned = []
                for c in calls:
                    fn = c.get("function", {})
                    try:
                        args = {k: v for k, v in json.loads(fn.get("arguments") or "{}").items() if v not in (None, "", "null")}
                    except json.JSONDecodeError:
                        args = {}
                    cleaned.append((c, fn.get("name", ""), args))
                oa_messages.append(m)
                if not calls:
                    final_text = (m.get("content") or "").strip()
                    break
                for c, name, args in cleaned:
                    if name == "save_caller" and not args:
                        content = "Error: nothing to save; the caller has not given a name or number yet. Do not call save_caller until they do."
                    else:
                        content = run_tool(name, args)
                    oa_messages.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": content})
            else:
                final_text = "Sorry, I could not complete that. Shall I connect you to a counsellor?"

        return final_text
    finally:
        _provider_now.reset(token)


def run_turn(db: Session, conversation_id: str, user_text: str) -> str | None:
    """Store the user's message, run the agent, store and return the reply.
    Returns None when a human owns the thread (muted): the console shows the message instead."""
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise ValueError("conversation not found; call get_or_create_conversation first")
    _capture_identity(conv, user_text)
    conv.updated_at = datetime.utcnow()
    db.add(Message(conversation_id=conversation_id, role="user", content=user_text))
    db.commit()
    if conv.muted:
        return None
    if is_off_topic_math(user_text):
        db.add(Message(conversation_id=conversation_id, role="assistant", content=OFF_TOPIC_REPLY))
        db.commit()
        return OFF_TOPIC_REPLY

    ctx = ToolContext(conversation_id=conversation_id, channel=conv.channel,
                      caller_phone=None if conv.phone.startswith("unknown") else conv.phone,
                      caller_name=conv.caller_name or None)
    system = build_system_prompt(db, ctx)
    from .knowledge import facts_for
    website_facts = facts_for(user_text)
    if website_facts:  # company questions: give the model the website text up front
        system = system + "\n" + website_facts
    messages = history(db, conversation_id)

    def run_tool(name: str, args: dict) -> str:
        try:
            content = json.dumps(dispatch(db, name, args, ctx), default=str)
        except tools.ToolError as e:
            db.rollback()
            content = f"Error: {e}"
        except Exception as e:  # bug or outage: tell the model, log the stack
            db.rollback()
            log.exception("tool %s failed", name)
            content = f"Error: {name} is unavailable right now ({type(e).__name__}). Apologise and offer a counsellor."
        db.add(Message(conversation_id=conversation_id, role="tool", content=f"{name}({json.dumps(args)}) -> {content[:2000]}"))
        return content

    provider, why = route(conv, user_text)
    tools_used = [0]

    def counted_tool(name: str, args: dict) -> str:
        tools_used[0] += 1
        return run_tool(name, args)

    try:
        final_text = _run_model(provider, system, messages, counted_tool)
        log.info("turn %s answered by %s (%s)", conversation_id, provider, why)
    except Exception as e:
        escalate = settings.llm_mode.lower() == "hybrid" and provider != settings.hybrid_complex_provider.lower()
        if not escalate or tools_used[0]:  # never re-run a turn that already did something (sent, saved, booked)
            raise
        complex_ = settings.hybrid_complex_provider.lower()
        log.warning("turn %s: %s failed (%s: %s); retrying on %s", conversation_id, provider, type(e).__name__, str(e)[:120], complex_)
        final_text = _run_model(complex_, system, history(db, conversation_id), counted_tool)

    # The model said "the website doesn't mention it" without looking: look it up and answer once more
    if (final_text and _NOT_ON_SITE.search(final_text) and not website_facts and not tools_used[0]):
        from .knowledge import get_company_info
        info = get_company_info(user_text)
        if info["results"]:
            facts = "\n".join(f"- {r['topic']}: {r['info'][:1200]}" for r in info["results"][:4])
            log.info("turn %s: model said 'not on the website' without checking; retrying with website facts", conversation_id)
            try:
                final_text = _run_model(provider, system + "\nWEBSITE FACTS FOR THIS QUESTION (from " + info["source"]
                                        + "; answer from these if they cover the question):\n" + facts,
                                        history(db, conversation_id), counted_tool) or final_text
            except Exception:
                log.exception("website-facts retry failed; keeping the first answer")

    if not final_text:
        final_text = "Sorry, could you say that again?"
    db.add(Message(conversation_id=conversation_id, role="assistant", content=final_text))
    db.commit()
    return final_text
