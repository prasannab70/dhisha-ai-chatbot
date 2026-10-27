"""The nine receptionist tools. One place for business logic: the HTTP router, the
agent loop, the Retell webhook and the tests all call these functions."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import lms, whatsapp
from .config import settings
from .db import Appointment, Conversation, Course, DemoSlot, Handoff, Lead, Message, MessageLog, Staff, WorkingHours
from .schemas import (
    BookIn, BrochureIn, CallbackIn, CoursesIn, DirectionsIn, HandoffIn, SlotsIn, ToolContext,
)

OFFICE_LATLNG = (12.9828, 77.7571)  # Arya Hub Mall, Hope Farm junction (approx.)
DEST = quote(settings.office_address)


class ToolError(Exception):
    """Raised for caller-facing problems; the agent receives the message and carries on."""


# ---------- helpers ----------

def _fmt_time(t: time) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


def _fmt_date(d: date) -> str:
    return d.strftime("%a, %d %b")


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise ToolError(f"Date must be YYYY-MM-DD, got '{s}'")


def _parse_time(s: str) -> time:
    s = s.strip().upper()
    for fmt in ("%H:%M", "%I:%M %p", "%I %p", "%I%p", "%H"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            pass
    raise ToolError(f"Time must be HH:MM (24h), got '{s}'")


def _norm_phone(p: str | None) -> str | None:
    if not p:
        return None
    from .speech import spoken_digits
    d = re.sub(r"\D", "", spoken_digits(str(p)))
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    if len(d) != 10 or d[0] not in "6789":
        raise ToolError(f"'{p}' does not look like an Indian mobile number; ask the caller to repeat it")
    return "+91 " + d[:5] + " " + d[5:]


def find_staff(db: Session, name: str | None) -> Staff | None:
    if not name:
        return None
    n = name.lower().strip()
    rows = db.scalars(select(Staff)).all()
    for s in rows:
        if s.name.lower() == n:
            return s
    for s in rows:
        parts = s.name.lower().split()
        if any(p in n or n in p for p in parts if len(p) > 2):
            return s
    return None


def find_course(db: Session, q: str | None) -> Course | None:
    if not q:
        return None
    n = q.lower().strip()
    rows = _active_courses(db)
    for c in rows:
        if c.id == n or c.name.lower() == n:
            return c
    for c in rows:
        if n in c.name.lower() or c.name.lower().split()[0] in n:
            return c
    return None


def _slots_counselling(db: Session, staff: Staff, d: date) -> list[time]:
    if staff.status == "out" and d == date.today():
        return []  # "Out" today blocks today's slots
    hours = db.scalars(select(WorkingHours).where(WorkingHours.staff_id == staff.id, WorkingHours.weekday == d.weekday())).all()
    if not hours:
        return []
    taken = {a.time for a in db.scalars(select(Appointment).where(
        Appointment.staff_id == staff.id, Appointment.date == d, Appointment.status == "confirmed")).all()}
    now = datetime.now()
    out: list[time] = []
    step = timedelta(minutes=settings.slot_minutes)
    for h in hours:
        cur = datetime.combine(d, h.start)
        end = datetime.combine(d, h.end)
        while cur + step <= end:
            t = cur.time()
            if t not in taken and cur > now + timedelta(minutes=30):
                out.append(t)
            cur += step
    return out


def _slots_demo(db: Session, d: date) -> list[time]:
    rows = db.scalars(select(DemoSlot).where(DemoSlot.weekday == d.weekday())).all()
    out = []
    for r in rows:
        booked = db.scalars(select(Appointment).where(
            Appointment.type == "demo", Appointment.date == d, Appointment.time == r.start,
            Appointment.status == "confirmed")).all()
        if len(booked) < r.capacity and datetime.combine(d, r.start) > datetime.now():
            out.append(r.start)
    return out


# ---------- the tools ----------

def _channel_code(ctx: ToolContext) -> str:
    """web | wa | call - how this person reached Disha (for the admin portal's source and follow-up channel)."""
    if ctx.channel == "call":
        return "call"
    return "wa" if (ctx.conversation_id or "").startswith("wa:") else "web"


def save_caller(db: Session, name: str | None, phone: str | None, ctx: ToolContext) -> dict:
    """Record the caller's name/number on the conversation and as a lead (once)."""
    conv = db.get(Conversation, ctx.conversation_id)
    if conv is None:
        raise ToolError("conversation not found")
    if name:
        conv.caller_name = name.strip().title()
    if phone:
        conv.phone = _norm_phone(phone)
    if conv.phone and not conv.phone.startswith("unknown"):
        exists = db.scalar(select(Lead).where(Lead.phone == conv.phone, Lead.note == "enquiry"))
        if not exists:
            db.add(Lead(name=conv.caller_name, phone=conv.phone, source="bot_call" if ctx.channel == "call" else "bot_chat", note="enquiry"))
            lms.queue(db, name=conv.caller_name, phone=conv.phone, channel=_channel_code(ctx), kind="enquiry",
                      note="gave their contact details", conversation_id=ctx.conversation_id)
    db.commit()
    return {"caller_name": conv.caller_name or None, "caller_phone": None if conv.phone.startswith("unknown") else conv.phone}


def _active_courses(db: Session) -> list[Course]:
    rows = db.scalars(select(Course)).all()
    active = [c for c in rows if getattr(c, "active", True) is not False]
    return active or rows


def get_courses(db: Session, inp: CoursesIn) -> list[dict]:
    from .knowledge import NOT_ANNOUNCED
    q = inp.query.lower().strip()
    rows = _active_courses(db)
    if q:
        rows = [c for c in rows if q in c.name.lower() or q in (c.suited_for or "").lower() or q == c.id
                or q in (c.details or "").lower()]
        # a course NAMED after the query ("Power BI" for "power") comes before one that only mentions it in its details
        rows.sort(key=lambda c: 0 if (q in c.name.lower() or q == c.id) else 1)
    return [{
        "id": c.id, "track": c.track, "name": c.name,
        "duration": c.duration_text or (f"{c.duration_weeks} weeks" if c.duration_weeks else "not published"),
        "fee": f"Rs {c.fee_inr:,}" if c.fee_inr else "not published on the website; a counsellor will share it",
        "mode_and_timings": c.mode or "not published on the website; a counsellor will share them",
        "next_batch": c.next_batch.isoformat() if c.next_batch and c.next_batch != NOT_ANNOUNCED else "not announced yet",
        "suited_for": c.suited_for, "what_you_learn": c.details or "",
    } for c in rows]


def get_available_staff(db: Session) -> list[dict]:
    return [{"name": s.name, "role": s.role, "status": s.status} for s in db.scalars(select(Staff)).all()]


# ---- Booking guardrails: enforced here, so a weaker model cannot skip them ----
_YES = re.compile(r"\b(yes|yeah|yea|yep|yup|ya|haan|haa|han|ha ji|ji|ok|okay|okk|okey|sure|confirm|confirmed|go ahead|proceed|"
                  r"book it|please do|do it|correct|right|fine|done|perfect|sounds good|theek|thik|chalega|absolutely|of course)\b")
_NO = re.compile(r"\b(no|nope|nah|not|don'?t|do not|wait|hold on|cancel|change|wrong|instead|nahi|nahin|mat|stop)\b")


def is_clear_yes(text: str) -> bool:
    t = (text or "").lower()
    return bool(_YES.search(t)) and not _NO.search(t)


def _lock_type(db: Session, ctx: ToolContext | None, wanted: str, changed_mind: bool = False) -> None:
    """Counselling vs demo is fixed for the conversation once chosen; switching needs the caller's explicit request."""
    conv = db.get(Conversation, ctx.conversation_id) if ctx else None
    if conv is None:
        return
    if conv.booking_type and conv.booking_type != wanted and not changed_mind:
        other = "a counselling session" if conv.booking_type == "counselling" else "a demo class"
        raise ToolError(f"The caller asked for {other} earlier, not {wanted}. Keep {conv.booking_type}. Only if the caller "
                        f"explicitly said they want to switch, call again with caller_changed_mind=true")
    conv.booking_type = wanted
    db.commit()


def get_slots(db: Session, inp: SlotsIn, ctx: ToolContext | None = None) -> dict:
    _lock_type(db, ctx, inp.type, inp.caller_changed_mind)
    d = _parse_date(inp.date)
    if d < date.today():
        raise ToolError("That date is in the past; ask for a date from today onwards")
    if inp.type == "counselling":
        staff = find_staff(db, inp.person)
        if not staff:
            names = ", ".join(s.name for s in db.scalars(select(Staff)).all())
            raise ToolError(f"No counsellor named '{inp.person}'. Counsellors: {names}")
        slots = _slots_counselling(db, staff, d)
        return {"type": "counselling", "person": staff.name, "date": d.isoformat(),
                "free_slots": [t.strftime("%H:%M") for t in slots[:8]]}
    slots = _slots_demo(db, d)
    return {"type": "demo", "person": "Demo class", "date": d.isoformat(),
            "free_slots": [t.strftime("%H:%M") for t in slots]}


def book_slot(db: Session, inp: BookIn, ctx: ToolContext) -> dict:
    d, t = _parse_date(inp.date), _parse_time(inp.time)
    to = _norm_phone(inp.confirm_to or inp.phone or ctx.caller_phone)
    if not to:
        raise ToolError("No contact number yet. Ask the caller for the WhatsApp number for the confirmation, then book")
    if inp.idempotency_key:
        existing = db.scalar(select(Appointment).where(Appointment.idempotency_key == inp.idempotency_key))
        if existing:
            return {"booking_id": existing.id, "status": "already_confirmed"}
    course = find_course(db, inp.course)
    staff = None
    if inp.type == "counselling":
        staff = find_staff(db, inp.person)
        if not staff:
            raise ToolError(f"No counsellor named '{inp.person}'")
        if t not in _slots_counselling(db, staff, d):
            raise ToolError(f"{_fmt_time(t)} on {_fmt_date(d)} is no longer free with {staff.name}. Offer another slot")
    else:
        if t not in _slots_demo(db, d):
            raise ToolError(f"No demo class at {_fmt_time(t)} on {_fmt_date(d)}. Offer the listed times")

    # Two-step confirmation: first call reads back, second call (after the caller's "yes") books.
    conv = db.get(Conversation, ctx.conversation_id)
    if conv is not None:
        _lock_type(db, ctx, inp.type)
        what0 = f"counselling session with {staff.name}" if staff else "free demo class"
        course0 = course.name if course else inp.course
        sig = json.dumps([inp.type, staff.id if staff else None, d.isoformat(), t.strftime("%H:%M"),
                          inp.student_name.strip().lower(), course.id if course else inp.course.lower(), to])
        summary = (f"{what0.capitalize()} for {inp.student_name.strip()}, {course0}, on {_fmt_date(d)} at {_fmt_time(t)}. "
                   f"Confirmation will go to WhatsApp {to}.")
        pending = json.loads(conv.pending_booking) if conv.pending_booking else None
        if not inp.confirmed or not pending or pending.get("sig") != sig:
            last_id = db.scalar(select(Message.id).where(Message.conversation_id == conv.id).order_by(Message.id.desc())) or 0
            conv.pending_booking = json.dumps({"sig": sig, "after_message": last_id})
            db.commit()
            changed = " (details changed since the last read-back)" if inp.confirmed and pending else ""
            return {"status": "needs_confirmation", "summary": summary,
                    "instruction": "NOT booked yet" + changed + ". Read this summary to the caller and ask 'Shall I confirm?'. "
                                   "Only after they say yes, call book_slot again with exactly the same details and confirmed=true."}
        if ctx.transcript_in_db:  # our agent recorded what the caller said; check their reply
            reply = db.scalar(select(Message).where(Message.conversation_id == conv.id, Message.role == "user",
                                                    Message.id > pending["after_message"]).order_by(Message.id.desc()))
            if reply is None:
                raise ToolError("Not booked: the caller has not answered the read-back yet. Ask 'Shall I confirm?' and wait for their reply")
            if not is_clear_yes(reply.content):
                raise ToolError(f"Not booked: the caller's reply ('{reply.content[:80]}') is not a clear yes. "
                                "Ask again, or change the details if they asked for a change")

    appt = Appointment(
        type=inp.type, staff_id=staff.id if staff else None, date=d, time=t,
        student_name=inp.student_name.strip(), phone=to, course_id=course.id if course else None,
        for_whom=inp.for_whom or "self", confirm_to=to,
        source="bot_call" if ctx.channel == "call" else "bot_chat",
        idempotency_key=inp.idempotency_key,
    )
    db.add(appt)
    db.add(Lead(name=inp.student_name, phone=to, course_id=course.id if course else None, source=appt.source, note="booked"))
    db.flush()

    what = f"Counselling with {staff.name}" if staff else "Demo class"
    course_name = course.name if course else inp.course
    lms.queue(db, name=inp.student_name, phone=to, channel=_channel_code(ctx), kind="booking",
              note=f"{what} on {_fmt_date(d)} at {_fmt_time(t)}", course_name=course_name,
              demo_on=d if not staff else None, priority="High", conversation_id=ctx.conversation_id)
    try:
        whatsapp.send_template(db, to, settings.wa_template_confirm,
                               [inp.student_name, what, course_name, f"{_fmt_date(d)} {_fmt_time(t)}", settings.office_address])
    except Exception as e:  # booking stands even if the send fails; the log shows it
        db.add(MessageLog(channel="whatsapp", to=to, kind="template:confirm", payload=str(e), status="failed"))
    if conv is not None:
        conv.pending_booking, conv.booking_type = None, None  # ready for a different booking later
    db.commit()
    return {"booking_id": appt.id, "status": "confirmed", "what": what, "course": course_name,
            "when": f"{_fmt_date(d)} {_fmt_time(t)}", "confirmation_sent_to": to,
            "reminder": f"{settings.reminder_minutes_before} minutes before"}


def send_brochure(db: Session, inp: BrochureIn, ctx: ToolContext) -> dict:
    course = find_course(db, inp.course_id)
    if not course:
        raise ToolError(f"Unknown course '{inp.course_id}'")
    to = _norm_phone(inp.phone)
    if not course.brochure_url:
        raise ToolError(f"No brochure file is on record for {course.name}; offer to have a counsellor send it")
    whatsapp.send_document(db, to, course.brochure_url, f"{course.name} - DhishaAI.pdf", f"{course.name} brochure")
    db.add(Lead(name=ctx.caller_name or "", phone=to, course_id=course.id, source="bot_call" if ctx.channel == "call" else "bot_chat", note="brochure"))
    lms.queue(db, name=ctx.caller_name, phone=to, channel=_channel_code(ctx), kind="brochure",
              note=f"brochure sent on WhatsApp", course_name=course.name, conversation_id=ctx.conversation_id)
    db.commit()
    return {"sent": True, "to": to, "file": f"{course.name} brochure"}


def get_office_address(db: Session, ctx: ToolContext) -> dict:
    link = f"https://www.google.com/maps/search/?api=1&query={DEST}"
    if ctx.channel == "chat" and ctx.caller_phone:
        try:
            whatsapp.send_location(db, ctx.caller_phone, *OFFICE_LATLNG, settings.office_name, settings.office_address)
            db.commit()
        except Exception:
            pass
    return {"name": settings.office_name, "address": settings.office_address, "landmark": settings.office_landmark,
            "nearest_metro": settings.office_metro, "phone_and_whatsapp": settings.office_phone, "email": settings.office_email,
            "hours": settings.office_hours or "not published on the website; please call before visiting",
            "visits": "Visitors are welcome; a meeting with the team can be booked", "maps_link": link}


# Indicative door-to-door minutes until the Google Routes API is wired in (week 3).
_AREAS = [
    (("majestic", "kempegowda"), "Majestic", 80, 65, 55, True),
    (("indiranagar",), "Indiranagar", 55, 45, 35, True),
    (("mg road", "trinity"), "MG Road", 65, 55, 45, True),
    (("marathahalli", "marathalli"), "Marathahalli", 35, 30, 22, False),
    (("kr puram", "k r puram", "tin factory"), "KR Puram", 35, 30, 22, True),
    (("mahadevapura",), "Mahadevapura", 25, 20, 15, True),
    (("electronic city", "ecity"), "Electronic City", 85, 70, 55, False),
    (("silk board", "hsr", "btm"), "Silk Board / HSR", 70, 60, 45, False),
    (("koramangala",), "Koramangala", 70, 55, 45, False),
    (("hebbal", "yelahanka", "manyata"), "Hebbal / Yelahanka", 80, 65, 55, False),
    (("sarjapur", "bellandur"), "Sarjapur / Bellandur", 50, 40, 30, False),
    (("hoskote", "kadugodi", "hope farm"), "Hoskote / Kadugodi", 20, 15, 12, True),
    (("jayanagar", "jp nagar", "banashankari"), "South Bengaluru", 85, 70, 55, False),
]


def get_directions(db: Session, inp: DirectionsIn) -> dict:
    n = inp.origin.lower()
    area = next((a for a in _AREAS if any(k in n for k in a[0])), None)
    name, bus, car, bike, metro = (area[1:] if area else (inp.origin, 60, 50, 40, False))
    mins = {"bus": bus, "car": car, "bike": bike}[inp.mode]
    tm = {"bus": "transit", "bike": "two-wheeler", "car": "driving"}[inp.mode]
    link = f"https://www.google.com/maps/dir/?api=1&origin={quote(inp.origin)}&destination={DEST}&travelmode={tm}"
    leave_by = None
    if inp.arrive_by:
        try:
            arr = datetime.combine(date.today(), _parse_time(inp.arrive_by)) - timedelta(minutes=mins + 10)
            leave_by = _fmt_time(arr.time())
        except ToolError:
            pass
    if inp.mode == "bus":
        route = ("Namma Metro Purple Line to Hopefarm Channasandra, then a 10-minute walk or auto to Arya Hub Mall."
                 if metro else
                 "BMTC bus towards Whitefield / Kadugodi via Marathahalli; get down at Hope Farm junction. Or reach the nearest Purple Line station and take the metro to Hopefarm Channasandra.")
    elif inp.mode == "bike":
        route = "Whitefield Main Road to Hope Farm junction; two-wheeler parking in the mall basement."
    else:
        route = "Via Marathahalli - Whitefield Main Road or ITPL Main Road to Hope Farm junction; car parking in the basement. Add 15 minutes in peak hours."
    return {"origin": inp.origin, "area": name, "mode": inp.mode, "estimated_minutes": mins,
            "suggested_route": route, "leave_by": leave_by or "n/a", "maps_link": link,
            "note": "Indicative; live timing in the Google Maps link"}


def handoff(db: Session, inp: HandoffIn, ctx: ToolContext) -> dict:
    staff = find_staff(db, inp.staff_name)
    if not staff:
        raise ToolError(f"No counsellor named '{inp.staff_name}'")
    if staff.status != "online":
        online = ", ".join(s.name for s in db.scalars(select(Staff).where(Staff.status == "online")).all()) or "nobody"
        raise ToolError(f"{staff.name} is {staff.status} right now. Online: {online}. Offer create_callback instead")
    h = Handoff(conversation_id=ctx.conversation_id, staff_id=staff.id, channel=ctx.channel, summary=inp.summary)
    db.add(h)
    conv = db.get(Conversation, ctx.conversation_id)
    if conv:
        conv.muted = True
    lms.queue(db, name=ctx.caller_name, phone=ctx.caller_phone, channel=_channel_code(ctx), kind="handoff",
              note=f"to {staff.name}: {inp.summary}", priority="High", conversation_id=ctx.conversation_id)
    db.commit()
    # chat: the console inbox picks it up; call: the voice platform reads transfer_to and dials it
    return {"transferred_to": staff.name, "transfer_to": staff.phone if ctx.channel == "call" else None,
            "whisper": inp.summary[:120], "status": "connected"}


def create_callback(db: Session, inp: CallbackIn, ctx: ToolContext) -> dict:
    to = _norm_phone(inp.phone or ctx.caller_phone)
    if not to:
        raise ToolError("Ask for the number to call back on")
    h = Handoff(conversation_id=ctx.conversation_id, staff_id=None, channel=ctx.channel, kind="callback",
                summary=f"{inp.name or ctx.caller_name or 'Caller'} ({to}): {inp.reason}",
                preferred_time=inp.preferred_time or "any time")
    db.add(h)
    db.add(Lead(name=inp.name or ctx.caller_name or "", phone=to, source="bot_call" if ctx.channel == "call" else "bot_chat", note=f"callback: {inp.reason}"))
    lms.queue(db, name=inp.name or ctx.caller_name, phone=to, channel=_channel_code(ctx), kind="callback",
              note=inp.reason, callback_time=h.preferred_time, priority="High", conversation_id=ctx.conversation_id)
    db.commit()
    return {"task_id": h.id, "status": "queued", "preferred_time": h.preferred_time}
