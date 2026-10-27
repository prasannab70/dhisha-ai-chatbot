"""Sends what Disha captures into the DhishaAI Admin Portal (the Node app: enquiries, follow-ups, students, fees).

Every lead, booking, brochure request and callback becomes an **Enquiry** in the portal, or a **follow-up** on the
enquiry that already exists for that phone number. Counsellors then work from the portal's Enquiries screen and
pipeline as they do today.

How it works
- tools.py calls queue(...) when it records something. That writes one row to the lms_sync table and nothing else,
  so a slow or stopped portal can never slow down or break a chat or a call.
- flush() (run right after a queue, and by the scheduler every minute) signs in to the portal with a dedicated
  account (LMS_EMAIL / LMS_PASSWORD in .env), looks the phone number up, and either creates the enquiry or adds a
  follow-up. Failures are kept with their error and retried; GET /admin/lms-status shows the queue.

Portal API used (src/routes/enquiries.routes.js in the portal):
  POST /api/auth/login {email,password}            -> cookie dhishaai_sid
  GET  /api/courses                                -> map Disha's course names to the portal's course ids
  GET  /api/enquiries?q=<phone>&open=1             -> find an open enquiry for that number
  POST /api/enquiries {name, phone(10 digits), course_id|course_other, source, priority, next_followup, demo_on, notes}
  POST /api/enquiries/:id/followups {remark, channel, next_date, outcome}
  PUT  /api/enquiries/:id ...                      -> set demo_on on an existing enquiry
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy import select

from .config import settings

log = logging.getLogger(__name__)
_lock = threading.Lock()
_client: httpx.Client | None = None
_courses: tuple[float, list[dict]] = (0.0, [])
MAX_ATTEMPTS = 12               # a minute apart at first, then the scheduler keeps trying for a day


def enabled() -> bool:
    return bool(settings.lms_url and settings.lms_email and settings.lms_password)


def _digits10(phone: str | None) -> str:
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d if len(d) == 10 else ""


# ---------------------------------------------------------------- queue (called from tools.py)

def queue(db, *, name: str | None, phone: str | None, channel: str, kind: str, note: str,
          course_name: str | None = None, demo_on: date | None = None, callback_time: str | None = None,
          priority: str = "Medium", conversation_id: str | None = None) -> None:
    """Remember one thing to send. kind: enquiry | booking | brochure | callback | handoff."""
    if not enabled():
        return
    digits = _digits10(phone)
    if not digits:
        return  # the portal needs a 10-digit number; without one there is nothing to file
    from .db import LmsSync
    payload = {"name": (name or "").strip(), "phone": digits, "channel": channel, "kind": kind, "note": note,
               "course_name": course_name or "", "demo_on": demo_on.isoformat() if demo_on else None,
               "callback_time": callback_time or "", "priority": priority, "conversation_id": conversation_id or "",
               "at": datetime.now().isoformat(timespec="seconds")}
    db.add(LmsSync(kind=kind, phone=digits, payload=json.dumps(payload, ensure_ascii=False)))
    db.flush()
    # send it as soon as the caller's transaction is committed (the scheduler also retries every minute)
    threading.Timer(2.0, flush).start()


# ---------------------------------------------------------------- portal client

def _login(force: bool = False) -> httpx.Client:
    global _client
    if _client is not None and not force:
        return _client
    c = httpx.Client(base_url=settings.lms_url.rstrip("/"), timeout=settings.lms_timeout_seconds, follow_redirects=True)
    r = c.post("/api/auth/login", json={"email": settings.lms_email, "password": settings.lms_password})
    if r.status_code >= 300:
        raise RuntimeError(f"portal sign-in failed ({r.status_code}): {r.text[:160]}")
    _client = c
    return c


def _call(method: str, path: str, **kw):
    """One portal request; signs in again once if the session has expired."""
    c = _login()
    r = c.request(method, path, **kw)
    if r.status_code == 401:
        c = _login(force=True)
        r = c.request(method, path, **kw)
    if r.status_code >= 300:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:200]}")
    return r.json() if r.content else {}


def portal_courses() -> list[dict]:
    global _courses
    if time.time() - _courses[0] > 600:
        data = _call("GET", "/api/courses")
        rows = data.get("rows", data) if isinstance(data, dict) else data
        _courses = (time.time(), [r for r in rows if r.get("active", 1)])
    return _courses[1]


def _course_fields(name: str) -> dict:
    """The portal's course id when a name matches, otherwise the name as 'course_other'."""
    n = (name or "").strip().lower()
    if not n:
        return {}
    for c in portal_courses():
        cn = (c.get("name") or "").lower()
        if cn == n or n in cn or cn in n:
            return {"course_id": c["id"]}
    return {"course_other": name.strip()}


def _find_open(phone: str) -> dict | None:
    data = _call("GET", "/api/enquiries", params={"q": phone, "open": "1", "limit": 20})
    for row in data.get("rows", []):
        if _digits10(row.get("phone")) == phone:
            return row
    return None


_SOURCE = {"web": "Website", "wa": "Other", "call": "Other"}
_FOLLOWUP_CHANNEL = {"wa": "WhatsApp", "call": "Call", "web": "Call"}
_HOW = {"web": "website chat", "wa": "WhatsApp", "call": "phone call"}


def _remark(p: dict) -> str:
    how = _HOW.get(p["channel"], p["channel"])
    head = {"enquiry": "Enquired", "booking": "Booked", "brochure": "Asked for a brochure", "callback": "Asked for a callback",
            "handoff": "Was connected to a counsellor"}.get(p["kind"], "Contacted")
    bits = [f"[Disha, {how}] {head}"]
    if p.get("course_name"):
        bits.append(f"course: {p['course_name']}")
    if p.get("note"):
        bits.append(p["note"])
    if p.get("callback_time"):
        bits.append(f"preferred time: {p['callback_time']}")
    return ". ".join(b.strip(". ") for b in bits if b) + "."


def _send(p: dict) -> int:
    """Create the enquiry or add a follow-up; returns the portal enquiry id."""
    today = date.today()
    next_fu = (today if p["kind"] in ("callback", "handoff") else today + timedelta(days=1)).isoformat()
    existing = _find_open(p["phone"])
    if existing:
        eid = existing["id"]
        _call("POST", f"/api/enquiries/{eid}/followups",
              json={"remark": _remark(p), "channel": _FOLLOWUP_CHANNEL.get(p["channel"], "Call"),
                    "next_date": next_fu, "outcome": {"booking": "Demo/counselling booked", "callback": "Callback requested"}.get(p["kind"], "")})
        if p.get("demo_on") and not existing.get("demo_on"):
            body = {k: existing.get(k) for k in ("name", "email", "phone", "city", "course_id", "course_other", "source",
                                                    "assigned_to", "status", "priority", "next_followup", "joined_on", "notes")}
            body["demo_on"] = p["demo_on"]
            body["next_followup"] = next_fu
            _call("PUT", f"/api/enquiries/{eid}", json=body)
        return eid
    body = {"name": p["name"] or ("Caller" if p["channel"] == "call" else "Website visitor"),
            "phone": p["phone"], "source": _SOURCE.get(p["channel"], "Other"),
            "priority": "High" if p["kind"] in ("booking", "callback", "handoff") else p.get("priority", "Medium"),
            "next_followup": next_fu, "demo_on": p.get("demo_on"), "notes": _remark(p),
            **_course_fields(p.get("course_name", ""))}
    out = _call("POST", "/api/enquiries", json=body)
    return int(out["id"])


# ---------------------------------------------------------------- flush (scheduler + right after a queue)

def flush() -> dict:
    """Send every pending row. Safe to call often; only one flush runs at a time."""
    if not enabled():
        return {"skipped": "LMS not configured"}
    if not _lock.acquire(blocking=False):
        return {"skipped": "already running"}
    sent = failed = 0
    try:
        from .db import LmsSync, SessionLocal
        db = SessionLocal()
        try:
            rows = db.scalars(select(LmsSync).where(LmsSync.status == "pending").order_by(LmsSync.id).limit(50)).all()
            for row in rows:
                p = json.loads(row.payload)
                try:
                    row.lms_enquiry_id = _send(p)
                    row.status, row.done_at, row.last_error = "done", datetime.now(), ""
                    sent += 1
                except Exception as e:
                    row.attempts += 1
                    row.last_error = str(e)[:300]
                    if row.attempts >= MAX_ATTEMPTS:
                        row.status = "failed"
                    failed += 1
                    log.warning("LMS sync %s (%s %s) failed, attempt %s: %s", row.id, p["kind"], p["phone"], row.attempts, row.last_error)
                db.commit()
        finally:
            db.close()
    finally:
        _lock.release()
    if sent:
        log.info("LMS sync: %s sent to the admin portal", sent)
    return {"sent": sent, "failed": failed}


def retry_failed() -> int:
    """Put every failed row back in the queue (POST /admin/lms-retry)."""
    from .db import LmsSync, SessionLocal
    db = SessionLocal()
    try:
        rows = db.scalars(select(LmsSync).where(LmsSync.status == "failed")).all()
        for r in rows:
            r.status, r.attempts = "pending", 0
        db.commit()
        return len(rows)
    finally:
        db.close()


def status() -> dict:
    from sqlalchemy import func
    from .db import LmsSync, SessionLocal
    db = SessionLocal()
    try:
        counts = dict(db.execute(select(LmsSync.status, func.count(LmsSync.id)).group_by(LmsSync.status)).all())
        last_done = db.scalar(select(func.max(LmsSync.done_at)))
        last_err = db.scalars(select(LmsSync).where(LmsSync.last_error != "").order_by(LmsSync.id.desc()).limit(1)).first()
        return {"configured": enabled(), "portal": settings.lms_url or None, "account": settings.lms_email or None,
                "pending": counts.get("pending", 0), "done": counts.get("done", 0), "failed": counts.get("failed", 0),
                "last_sent_at": last_done.isoformat() if last_done else None,
                "last_error": last_err.last_error if last_err else None}
    finally:
        db.close()


def check() -> dict:
    """Sign in and read the course list: proves the address, the account and the password (POST /admin/lms-check)."""
    if not enabled():
        raise RuntimeError("Set LMS_URL, LMS_EMAIL and LMS_PASSWORD in .env first")
    _login(force=True)
    return {"ok": True, "courses_in_portal": len(portal_courses())}
