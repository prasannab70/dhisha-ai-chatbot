"""Read/write endpoints for the receptionist screen (any front end: React, Streamlit, or the demo page)."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import whatsapp
from ..db import Appointment, Conversation, Handoff, Lead, Message, MessageLog, Staff, get_session
from .tools import require_token

router = APIRouter(prefix="/console", tags=["console"], dependencies=[Depends(require_token)])


@router.get("/summary")
def summary(db: Session = Depends(get_session)):
    today = date.today()
    appts = db.scalars(select(Appointment).where(Appointment.status == "confirmed")).all()
    return {
        "bookings_today": sum(1 for a in appts if a.date == today),
        "bookings_by_bot": sum(1 for a in appts if a.source != "manual"),
        "handoffs_waiting": db.query(Handoff).filter(Handoff.done.is_(False)).count(),
        "leads": db.query(Lead).count(),
    }


@router.get("/staff")
def staff(db: Session = Depends(get_session)):
    return [{"id": s.id, "name": s.name, "role": s.role, "status": s.status} for s in db.scalars(select(Staff)).all()]


class StatusIn(BaseModel):
    status: str  # online | busy | out


@router.put("/staff/{staff_id}/status")
def set_status(staff_id: int, inp: StatusIn, db: Session = Depends(get_session)):
    if inp.status not in ("online", "busy", "out"):
        raise HTTPException(422, "status must be online, busy or out")
    s = db.get(Staff, staff_id)
    if not s:
        raise HTTPException(404, "no such staff")
    s.status = inp.status
    db.commit()
    return {"id": s.id, "status": s.status}


@router.get("/appointments")
def appointments(from_date: date | None = None, db: Session = Depends(get_session)):
    q = select(Appointment).where(Appointment.date >= (from_date or date.today())).order_by(Appointment.date, Appointment.time)
    rows = db.scalars(q).all()
    staff = {s.id: s.name for s in db.scalars(select(Staff)).all()}
    return [{
        "id": a.id, "type": a.type, "date": a.date.isoformat(), "time": a.time.strftime("%H:%M"),
        "student": a.student_name, "course": a.course_id, "with": staff.get(a.staff_id, "Demo class"),
        "confirm_to": a.confirm_to, "source": a.source, "status": a.status, "booked_at": a.created_at.isoformat(),
    } for a in rows]


@router.get("/leads")
def leads(db: Session = Depends(get_session)):
    rows = db.scalars(select(Lead).order_by(Lead.created_at.desc()).limit(100)).all()
    return [{"id": l.id, "name": l.name, "phone": l.phone, "course": l.course_id, "note": l.note, "source": l.source, "at": l.created_at.isoformat()} for l in rows]


@router.get("/handoffs")
def handoffs(db: Session = Depends(get_session)):
    staff = {s.id: s.name for s in db.scalars(select(Staff)).all()}
    rows = db.scalars(select(Handoff).order_by(Handoff.created_at.desc()).limit(50)).all()
    return [{
        "id": h.id, "conversation_id": h.conversation_id, "staff": staff.get(h.staff_id, "Any counsellor"),
        "channel": h.channel, "kind": h.kind, "summary": h.summary, "preferred_time": h.preferred_time,
        "done": h.done, "at": h.created_at.isoformat(),
    } for h in rows]


@router.get("/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: str, tools: bool = False, db: Session = Depends(get_session)):
    rows = db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)).all()
    return [{"role": m.role, "content": m.content, "at": m.created_at.isoformat()} for m in rows if tools or m.role != "tool"]


class ReplyIn(BaseModel):
    text: str
    staff_name: str


@router.post("/conversations/{conversation_id}/reply")
def human_reply(conversation_id: str, inp: ReplyIn, db: Session = Depends(get_session)):
    """A counsellor answers inside the caller's WhatsApp thread (chat handoffs only)."""
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, "no such conversation")
    db.add(Message(conversation_id=conversation_id, role="human", content=f"{inp.staff_name}: {inp.text}"))
    _whatsapp_if_needed(db, conv, f"{inp.staff_name} here: {inp.text}")
    db.commit()
    return {"ok": True}


def _whatsapp_if_needed(db: Session, conv: Conversation, text: str) -> None:
    """Only WhatsApp threads (wa:...) get a WhatsApp message; website and demo chats read the thread itself.
    A failed send is logged, never allowed to break the console action."""
    if not conv.id.startswith("wa:"):
        return
    try:
        whatsapp.send_text(db, conv.phone, text)
    except Exception as e:
        db.add(MessageLog(channel="whatsapp", to=conv.phone or "", kind="text", payload=str(e)[:300], status="failed"))


@router.post("/handoffs/{handoff_id}/release")
def release(handoff_id: int, db: Session = Depends(get_session)):
    """Give the thread back to Disha."""
    h = db.get(Handoff, handoff_id)
    if not h:
        raise HTTPException(404, "no such handoff")
    h.done = True
    conv = db.get(Conversation, h.conversation_id)
    if conv:
        conv.muted = False
        text = "Disha here again. Anything else I can help with?"
        db.add(Message(conversation_id=conv.id, role="assistant", content=text))
        _whatsapp_if_needed(db, conv, text)
    db.commit()
    return {"ok": True}


@router.get("/message_log")
def message_log(db: Session = Depends(get_session)):
    rows = db.scalars(select(MessageLog).order_by(MessageLog.created_at.desc()).limit(50)).all()
    return [{"channel": m.channel, "to": m.to, "kind": m.kind, "status": m.status, "at": m.created_at.isoformat()} for m in rows]


@router.get("/conversations")
def conversations(limit: int = 100, db: Session = Depends(get_session)):
    """Latest conversations across every channel, newest first (for the admin side)."""
    rows = db.scalars(select(Conversation).order_by(Conversation.updated_at.desc()).limit(min(limit, 500))).all()
    from sqlalchemy import func
    counts = dict(db.execute(select(Message.conversation_id, func.count(Message.id))
                             .where(Message.role.in_(("user", "assistant", "human"))).group_by(Message.conversation_id)).all())
    return [{"id": c.id, "channel": c.channel, "phone": c.phone, "name": c.caller_name, "muted": c.muted,
             "messages": counts.get(c.id, 0), "updated_at": c.updated_at.isoformat()} for c in rows]


# ---- Data: every table, for the admin side (JSON pages, and the whole table as CSV) ----
from ..db import Base as _Base

TABLES = {t.name: t for t in _Base.metadata.sorted_tables}


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    if hasattr(v, "strftime"):   # time
        return v.strftime("%H:%M")
    if isinstance(v, bool):
        return "yes" if v else "no"
    return v


@router.get("/tables")
def tables(db: Session = Depends(get_session)):
    """Every table with its row count and columns."""
    from sqlalchemy import func
    out = []
    for name, t in TABLES.items():
        n = db.execute(select(func.count()).select_from(t)).scalar() or 0
        out.append({"table": name, "rows": n, "columns": [c.name for c in t.columns]})
    return out


def _table(name: str):
    t = TABLES.get(name)
    if t is None:
        raise HTTPException(404, f"no such table; one of {', '.join(TABLES)}")
    return t


@router.get("/tables/{name}")
def table_rows(name: str, limit: int = 200, offset: int = 0, db: Session = Depends(get_session)):
    """One page of a table, newest first when it has an id."""
    t = _table(name)
    q = select(t)
    if "id" in t.columns:
        q = q.order_by(t.c.id.desc())
    rows = db.execute(q.offset(max(offset, 0)).limit(max(1, min(limit, 1000)))).all()
    return {"table": name, "columns": [c.name for c in t.columns], "offset": offset,
            "rows": [[_cell(v) for v in r] for r in rows]}


@router.get("/tables/{name}/csv")
def table_csv(name: str, db: Session = Depends(get_session)):
    """The whole table as a CSV file (Excel opens it directly)."""
    import csv
    import io
    from fastapi.responses import StreamingResponse
    t = _table(name)
    q = select(t)
    if "id" in t.columns:
        q = q.order_by(t.c.id)

    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([c.name for c in t.columns])
        yield "﻿" + buf.getvalue()  # BOM so Excel reads UTF-8 (names, rupee symbols) correctly
        buf.seek(0); buf.truncate()
        for r in db.execute(q).yield_per(500):
            w.writerow([_cell(v) for v in r])
            yield buf.getvalue()
            buf.seek(0); buf.truncate()

    stamp = datetime.now().strftime("%Y-%m-%d")
    return StreamingResponse(gen(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}-{stamp}.csv"'})
