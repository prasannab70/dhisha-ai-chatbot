"""Pydantic request/response models for the 9 tools."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CoursesIn(BaseModel):
    query: str = ""


class SlotsIn(BaseModel):
    type: Literal["counselling", "demo"]
    date: str = Field(description="YYYY-MM-DD")
    person: str | None = None
    caller_changed_mind: bool = False   # only true when the caller explicitly switched counselling <-> demo


class BookIn(BaseModel):
    type: Literal["counselling", "demo"]
    date: str
    time: str = Field(description="HH:MM, 24h")
    student_name: str
    course: str
    phone: str | None = None
    person: str | None = None
    for_whom: str = "self"
    confirm_to: str | None = None
    confirmed: bool = False             # false = validate and read back; true = book (only after the caller said yes)
    idempotency_key: str | None = None


class BrochureIn(BaseModel):
    course_id: str
    phone: str


class DirectionsIn(BaseModel):
    origin: str
    mode: Literal["bus", "bike", "car"]
    arrive_by: str | None = None


class HandoffIn(BaseModel):
    staff_name: str
    summary: str


class CallbackIn(BaseModel):
    reason: str
    phone: str | None = None
    name: str | None = None
    preferred_time: str | None = None


class ToolContext(BaseModel):
    """Who is calling the tool: set by the channel, not by the model."""
    conversation_id: str
    channel: Literal["chat", "call"] = "chat"
    caller_phone: str | None = None
    caller_name: str | None = None
    # False only when another system (Retell's own model) holds the transcript, so the caller's "yes" cannot be checked here
    transcript_in_db: bool = True
