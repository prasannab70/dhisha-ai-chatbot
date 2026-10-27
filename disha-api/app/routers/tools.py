"""HTTP face of the nine tools (for Retell custom functions, the console, tests, or any other caller)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import tools
from ..config import settings
from ..db import get_session
from ..schemas import (
    BookIn, BrochureIn, CallbackIn, CoursesIn, DirectionsIn, HandoffIn, SlotsIn, ToolContext,
)

router = APIRouter(prefix="/tools", tags=["tools"])


def require_token(authorization: str = Header(default="")) -> None:
    if authorization != f"Bearer {settings.console_token}":
        raise HTTPException(401, "bad token")


def ctx_from(conversation_id: str = "api", channel: str = "chat", caller_phone: str | None = None, caller_name: str | None = None) -> ToolContext:
    return ToolContext(conversation_id=conversation_id, channel=channel, caller_phone=caller_phone, caller_name=caller_name)


def run(fn, *a):
    try:
        return fn(*a)
    except tools.ToolError as e:
        raise HTTPException(422, str(e))


class CallerIn(BaseModel):
    name: str | None = None
    phone: str | None = None


@router.post("/save_caller", dependencies=[Depends(require_token)])
def save_caller(inp: CallerIn, ctx: ToolContext = Depends(ctx_from), db: Session = Depends(get_session)):
    from .. import agent
    agent.get_or_create_conversation(db, ctx.conversation_id, ctx.channel, ctx.caller_phone, ctx.caller_name or "")
    return run(tools.save_caller, db, inp.name, inp.phone, ctx)


@router.post("/get_courses", dependencies=[Depends(require_token)])
def get_courses(inp: CoursesIn, db: Session = Depends(get_session)):
    return run(tools.get_courses, db, inp)


@router.api_route("/get_available_staff", methods=["GET", "POST"], dependencies=[Depends(require_token)])
def get_available_staff(db: Session = Depends(get_session)):
    return tools.get_available_staff(db)


@router.post("/get_slots", dependencies=[Depends(require_token)])
def get_slots(inp: SlotsIn, ctx: ToolContext = Depends(ctx_from), db: Session = Depends(get_session)):
    return run(tools.get_slots, db, inp, ctx)


@router.post("/book_slot", dependencies=[Depends(require_token)])
def book_slot(inp: BookIn, ctx: ToolContext = Depends(ctx_from), db: Session = Depends(get_session)):
    return run(tools.book_slot, db, inp, ctx)


@router.post("/send_brochure", dependencies=[Depends(require_token)])
def send_brochure(inp: BrochureIn, ctx: ToolContext = Depends(ctx_from), db: Session = Depends(get_session)):
    return run(tools.send_brochure, db, inp, ctx)


@router.api_route("/get_office_address", methods=["GET", "POST"], dependencies=[Depends(require_token)])
def get_office_address(ctx: ToolContext = Depends(ctx_from), db: Session = Depends(get_session)):
    return tools.get_office_address(db, ctx)


@router.post("/get_directions", dependencies=[Depends(require_token)])
def get_directions(inp: DirectionsIn, db: Session = Depends(get_session)):
    return run(tools.get_directions, db, inp)


@router.post("/handoff", dependencies=[Depends(require_token)])
def handoff(inp: HandoffIn, ctx: ToolContext = Depends(ctx_from), db: Session = Depends(get_session)):
    return run(tools.handoff, db, inp, ctx)


@router.post("/create_callback", dependencies=[Depends(require_token)])
def create_callback(inp: CallbackIn, ctx: ToolContext = Depends(ctx_from), db: Session = Depends(get_session)):
    return run(tools.create_callback, db, inp, ctx)
