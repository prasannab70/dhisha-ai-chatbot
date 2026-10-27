"""Retell AI custom-function webhook.

In the Retell dashboard, create one custom function per tool with URL
  POST https://<your-host>/webhooks/retell/<tool_name>
and header  X-Retell-Secret: <RETELL_SECRET>.
Retell posts {"call": {...}, "name": "<tool>", "args": {...}}; we answer with the tool's JSON.
For handoff, the response carries transfer_to; configure Retell's transfer_call to use it,
or use Retell's built-in transfer with a dynamic variable set from this response.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .. import agent, tools
from ..config import settings
from ..db import get_session
from ..schemas import ToolContext

router = APIRouter(prefix="/webhooks/retell", tags=["retell"])


def _ctx(call: dict) -> ToolContext:
    call_id = call.get("call_id", "unknown")
    phone = call.get("from_number")
    dyn = call.get("retell_llm_dynamic_variables", {}) or {}
    return ToolContext(conversation_id=f"call:{call_id}", channel="call",
                       caller_phone=phone, caller_name=dyn.get("caller_name"),
                       transcript_in_db=False)


@router.post("/{tool_name}")
async def retell_tool(tool_name: str, request: Request, db: Session = Depends(get_session),
                      x_retell_secret: str = Header(default="")):
    if x_retell_secret != settings.retell_secret:
        raise HTTPException(401, "bad secret")
    body = await request.json()
    call = body.get("call", {})
    args = body.get("args", {}) or {}
    ctx = _ctx(call)
    agent.get_or_create_conversation(db, ctx.conversation_id, "call", ctx.caller_phone, ctx.caller_name or "")
    try:
        return agent.dispatch(db, tool_name, args, ctx)
    except tools.ToolError as e:
        return {"error": str(e)}
