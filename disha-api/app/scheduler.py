"""Background jobs: reminder before each appointment, and a daily follow-up for leads
who asked for a brochure but never booked. Runs inside the API process (APScheduler);
move to a separate worker if the API scales to more than one instance."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from . import whatsapp
from .config import settings
from .db import Appointment, Lead, SessionLocal

log = logging.getLogger(__name__)
def _tz():
    from zoneinfo import ZoneInfo
    for name in (settings.tz, "Asia/Kolkata", "UTC"):
        try:
            return ZoneInfo(name)
        except Exception:
            continue
    return None


scheduler = BackgroundScheduler(timezone=_tz())


def send_reminders() -> None:
    """Every 5 minutes: WhatsApp template to anyone whose appointment starts in the next window."""
    db = SessionLocal()
    try:
        now = datetime.now()
        lo, hi = now + timedelta(minutes=settings.reminder_minutes_before - 5), now + timedelta(minutes=settings.reminder_minutes_before + 5)
        rows = db.scalars(select(Appointment).where(
            Appointment.status == "confirmed", Appointment.reminder_sent.is_(False), Appointment.date == lo.date())).all()
        for a in rows:
            start = datetime.combine(a.date, a.time)
            if lo <= start <= hi:
                what = "demo class" if a.type == "demo" else "counselling session"
                try:
                    whatsapp.send_template(db, a.confirm_to, settings.wa_template_reminder,
                                           [a.student_name, what, start.strftime("%I:%M %p").lstrip("0"), settings.office_address])
                    a.reminder_sent = True
                except Exception:
                    log.exception("reminder failed for appointment %s", a.id)
        db.commit()
    finally:
        db.close()


def follow_up_leads() -> None:
    """Daily 11:00: nudge leads who got a brochure 2 days ago and have no booking. Respect calling hours."""
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=2)
        leads = db.scalars(select(Lead).where(Lead.note == "brochure", Lead.created_at <= cutoff)).all()
        booked = {a.phone for a in db.scalars(select(Appointment)).all()}
        for l in leads:
            if l.phone in booked:
                continue
            # Business-initiated: must be an approved template outside the 24-hour window.
            try:
                whatsapp.send_template(db, l.phone, "brochure_follow_up", [l.name or "there"])
                l.note = "brochure_followed_up"
            except Exception:
                log.exception("follow-up failed for lead %s", l.id)
        db.commit()
    finally:
        db.close()


def start() -> None:
    from . import wp_sync
    if settings.wp_base_url:
        scheduler.add_job(wp_sync.sync_courses, "interval", minutes=settings.wp_sync_minutes, id="wp_courses", replace_existing=True, next_run_time=datetime.now(_tz()))
    scheduler.add_job(send_reminders, "interval", minutes=5, id="reminders", replace_existing=True)
    from . import lms
    if lms.enabled():  # anything not yet delivered to the admin portal
        scheduler.add_job(lms.flush, "interval", minutes=1, id="lms_sync", replace_existing=True)
    scheduler.add_job(follow_up_leads, "cron", hour=11, minute=0, id="follow_up", replace_existing=True)
    if settings.website_refresh_enabled:
        from . import site_refresh
        hours = max(1, settings.website_refresh_hours)
        scheduler.add_job(site_refresh.refresh, "interval", hours=hours, id="website_refresh", replace_existing=True)
        last = site_refresh.load().get("refreshed_at")
        stale = not last or (datetime.now() - datetime.fromisoformat(last)).total_seconds() > hours * 3600
        if stale:  # first run, or the server was off: refresh in the background a few seconds after startup
            scheduler.add_job(site_refresh.refresh, "date", run_date=datetime.now(_tz()) + timedelta(seconds=10),
                              id="website_refresh_now", replace_existing=True)
    scheduler.start()
