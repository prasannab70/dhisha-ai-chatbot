"""Example data so the API runs out of the box. Replace with DhishaAI's real courses and staff.
    python -m app.seed
"""
from __future__ import annotations

from datetime import date, time, timedelta

from sqlalchemy import select

from .db import Course, DemoSlot, SessionLocal, Staff, WorkingHours, init_db


def seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        if db.scalar(select(Course)):
            print("already seeded")
            return
        today = date.today()
        today = date.today()
        courses = [
            Course(id="sql", track="Analytics & BI", name="SQL for Analytics", fee_inr=12000, duration_weeks=4, mode="Weekend & weekday evening", next_batch=today + timedelta(days=9), suited_for="Beginners, anyone starting analytics"),
            Course(id="pbi", track="Analytics & BI", name="Power BI", fee_inr=18000, duration_weeks=6, mode="Weekend", next_batch=today + timedelta(days=11), suited_for="Business users, MIS, finance, BI aspirants"),
            Course(id="py", track="Programming & Data Science", name="Python for Data Science", fee_inr=22000, duration_weeks=8, mode="Weekday evening", next_batch=today + timedelta(days=16), suited_for="Graduates, working professionals moving to data"),
            Course(id="ds", track="Programming & Data Science", name="Data Science & ML Program", fee_inr=65000, duration_weeks=20, mode="Weekend + labs", next_batch=today + timedelta(days=23), suited_for="Career switch to data scientist; includes capstone & placement support"),
            Course(id="de", track="Data Engineering & Cloud", name="Data Engineering (Cloud)", fee_inr=55000, duration_weeks=16, mode="Weekend", next_batch=today + timedelta(days=30), suited_for="Developers / DBAs moving to data platforms (AWS, Azure)"),
            Course(id="genai", track="AI & GenAI", name="GenAI & LLM Applications", fee_inr=35000, duration_weeks=8, mode="Weekend", next_batch=today + timedelta(days=18), suited_for="Developers and analysts building AI apps"),
            Course(id="tab", track="Analytics & BI", name="Tableau", fee_inr=16000, duration_weeks=5, mode="Weekday evening", next_batch=today + timedelta(days=13), suited_for="BI / reporting roles"),
        ]
        db.add_all(courses)
        db.flush()
        from .knowledge import apply_website_courses
        apply_website_courses(db)  # plus the four programmes listed on dhishaai.com
        staff = [
            Staff(name="Anita Rao", role="Senior counsellor - BI & Analytics", phone="+91 98450 00010", status="online"),
            Staff(name="Suresh Kumar", role="Counsellor - Data Science & GenAI", phone="+91 99000 00027", status="busy"),
            Staff(name="Priya Nair", role="Counsellor - Data Engineering & Cloud", phone="+91 97400 00041", status="online"),
            Staff(name="Vikram Shetty", role="Placement & corporate training", phone="+91 98860 00019", status="out"),
        ]
        db.add_all(staff)
        db.flush()
        for s in staff[:3]:
            for wd in range(0, 6):  # Mon-Sat
                db.add(WorkingHours(staff_id=s.id, weekday=wd, start=time(10, 0), end=time(18, 0)))
        db.add_all([
            DemoSlot(weekday=5, start=time(11, 0)), DemoSlot(weekday=5, start=time(15, 0)),
            DemoSlot(weekday=6, start=time(11, 0)), DemoSlot(weekday=6, start=time(15, 0)),
            *[DemoSlot(weekday=wd, start=time(18, 30)) for wd in range(0, 5)],
        ])
        db.commit()
        print("seeded")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
