"""Which phone company's number Disha uses, and tidy caller numbers from either one.

Both numbers are imported into Retell and point at the same agent, so incoming calls work on whichever number
people dial. PHONE_PROVIDER only decides the number Disha calls OUT from; switch it in .env or with
PUT /phone/line (until restart).
"""
from __future__ import annotations

import re

from .config import settings

LINES = ("plivo", "exotel")


def e164(number: str | None) -> str:
    """'+91 80712 34567', '08071234567', '918071234567' -> '+918071234567' ('' if not a number)."""
    d = re.sub(r"\D", "", number or "")
    if not d:
        return ""
    if len(d) == 11 and d.startswith("0"):        # Exotel often sends 0-prefixed Indian numbers
        d = "91" + d[1:]
    elif len(d) == 10:
        d = "91" + d
    return "+" + d


def number_of(line: str) -> str:
    return e164(getattr(settings, f"{line}_number", ""))


def active() -> dict:
    line = settings.phone_provider.lower()
    return {"provider": line, "number": number_of(line) if line in LINES else ""}


def line_for(to_number: str | None) -> str:
    """Which company carried an incoming call (by the number the caller dialled)."""
    n = e164(to_number)
    for line in LINES:
        if n and n == number_of(line):
            return line
    return "unknown"


def caller(from_number: str | None) -> str | None:
    """The caller's number in the same style the tools use ('+91 98765 43210'); other numbers kept as +E164."""
    n = e164(from_number)
    if not n:
        return None
    d = n[1:]
    if len(d) == 12 and d.startswith("91") and d[2] in "6789":
        return f"+91 {d[2:7]} {d[7:]}"
    return n
