"""Database models and session (MySQL). Tables are created on first start; sql/schema.sql has the same DDL."""
from __future__ import annotations

from datetime import datetime, date, time
from typing import Iterator

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import settings

_local_test = settings.database_url.startswith("sqlite") and settings.allow_local_test_db
if not settings.database_url.startswith("mysql") and not _local_test:
    raise RuntimeError(
        "DATABASE_URL must be a MySQL address, e.g. "
        "mysql+pymysql://disha:<password>@localhost:3306/disha?charset=utf8mb4 "
        "(create the database with: mysql -u root -p < sql/schema.sql). "
        "To try the app on a laptop without MySQL, set ALLOW_LOCAL_TEST_DB=true and DATABASE_URL=sqlite:///./local-test.db "
        "(a throwaway file; not for real use).")

engine = create_engine(
    settings.database_url,
    **({"connect_args": {"check_same_thread": False}} if _local_test else
       {"pool_pre_ping": True,      # MySQL drops idle connections; check before use instead of failing a request
        "pool_recycle": 1800, "pool_size": 5, "max_overflow": 10}),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    track: Mapped[str] = mapped_column(String(60), default="")
    fee_inr: Mapped[int] = mapped_column(Integer)
    duration_weeks: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(80))
    next_batch: Mapped[date] = mapped_column(Date)
    suited_for: Mapped[str] = mapped_column(Text)
    brochure_url: Mapped[str] = mapped_column(String(300), default="")
    # fee_inr 0 / mode "" = not published; duration_text and details come from the website (app/knowledge.py)
    duration_text: Mapped[str | None] = mapped_column(String(40), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Staff(Base):
    __tablename__ = "staff"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    role: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))
    # right-now presence, set from the console: online | busy | out
    status: Mapped[str] = mapped_column(String(10), default="out")
    takes_bookings: Mapped[bool] = mapped_column(Boolean, default=True)


class WorkingHours(Base):
    """When a counsellor can take counselling bookings (weekday 0=Mon ... 6=Sun)."""
    __tablename__ = "working_hours"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    weekday: Mapped[int] = mapped_column(Integer)
    start: Mapped[time] = mapped_column(Time)
    end: Mapped[time] = mapped_column(Time)


class DemoSlot(Base):
    """Fixed demo-class times (weekday 0=Mon ... 6=Sun)."""
    __tablename__ = "demo_slots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    weekday: Mapped[int] = mapped_column(Integer)
    start: Mapped[time] = mapped_column(Time)
    capacity: Mapped[int] = mapped_column(Integer, default=10)


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_appt_idem"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(12))  # counselling | demo
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"), nullable=True)
    date: Mapped[date] = mapped_column(Date)
    time: Mapped[time] = mapped_column(Time)
    student_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    for_whom: Mapped[str] = mapped_column(String(120), default="self")
    confirm_to: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(12))  # bot_chat | bot_call | manual
    status: Mapped[str] = mapped_column(String(12), default="confirmed")
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(20))
    course_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(12))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Handoff(Base):
    __tablename__ = "handoffs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(40))
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(8))  # chat | call
    summary: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(10), default="handoff")  # handoff | callback
    preferred_time: Mapped[str] = mapped_column(String(60), default="")
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    """One per caller phone number. muted = a human owns the thread."""
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # wa:<phone> or call:<id>
    phone: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(8))
    caller_name: Mapped[str] = mapped_column(String(120), default="")
    muted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Booking guardrails (enforced in tools.book_slot / get_slots, not by the prompt)
    booking_type: Mapped[str | None] = mapped_column(String(12), nullable=True)     # counselling | demo, locked once chosen
    pending_booking: Mapped[str | None] = mapped_column(Text, nullable=True)        # JSON: details read back, awaiting "yes"


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(10))  # user | assistant | human | tool
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MessageLog(Base):
    """Outbound sends: WhatsApp templates, documents, emails, reminders."""
    __tablename__ = "message_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(10))  # whatsapp | email | call
    to: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="sent")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LmsSync(Base):
    """Outbox for the DhishaAI Admin Portal (app/lms.py): one row per lead/booking/callback to send, with retries."""
    __tablename__ = "lms_sync"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(12))        # enquiry | booking | brochure | callback | handoff
    phone: Mapped[str] = mapped_column(String(12))
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending")   # pending | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(300), default="")
    lms_enquiry_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Tiny migration for databases created before a column existed (create_all never alters tables)."""
    from sqlalchemy import inspect, text
    wanted = {"conversations": {"booking_type": "VARCHAR(12)", "pending_booking": "TEXT"},
              "courses": {"duration_text": "VARCHAR(40)", "details": "TEXT", "active": "BOOL DEFAULT 1"}}
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in wanted.items():
            have = {c["name"] for c in insp.get_columns(table)}
            for name, sqltype in cols.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sqltype}"))


def get_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
