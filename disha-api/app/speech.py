"""Turn chat-style text into something a voice can read naturally (used only on phone calls)."""
from __future__ import annotations

import re
from datetime import date

_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _iso_date(m: re.Match) -> str:
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return m.group(0)
    return f"{_DAYS[d.weekday()]}, {d.day} {_MONTHS[d.month - 1]}"


def _clock(m: re.Match) -> str:
    h, mins, ampm = int(m.group(1)), int(m.group(2)), (m.group(3) or "").strip().upper()
    if not ampm:
        if h > 23 or mins > 59:
            return m.group(0)
        ampm = "AM" if h < 12 else "PM"
        h = h % 12 or 12
    return f"{h} {ampm}" if mins == 0 else f"{h}:{mins:02d} {ampm}"


def _phone_aloud(m: re.Match) -> str:
    """Phone numbers are read digit by digit, in two groups, so the voice never says 'ninety-eight thousand...'."""
    return " ".join(m.group(1)) + ", " + " ".join(m.group(2))


def speakable(text: str) -> str:
    if not text:
        return text
    t = text
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", t)                 # [label](url) -> label
    t = re.sub(r"https?://\S+", "", t)                                        # bare links are never read out
    t = re.sub(r"[*_`#>]+", "", t)                                            # markdown symbols
    t = re.sub(r"(?m)^\s*(?:[-•–]|\d+[.)])\s+", "", t)                        # list bullets / numbers at line start
    t = re.sub(r"\s*\n+\s*", ". ", t)                                         # line breaks -> sentence breaks
    t = re.sub(r"(?:Rs\.?|INR|₹)\s?(\d[\d,]*\d|\d)(?:/-)?", r"\1 rupees", t)          # Rs 18,000 -> 18,000 rupees
    t = re.sub(r"(?:\+?91[\s-]?)?\b([6-9]\d{4})[\s-]?(\d{5})\b", _phone_aloud, t)     # 98765 43210 -> 9 8 7 6 5, 4 3 2 1 0
    t = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", _iso_date, t)                  # 2026-10-30 -> Friday, 30 October
    t = re.sub(r"\b(\d{1,2}):(\d{2})(\s?[AaPp][Mm])?\b", _clock, t)           # 15:00 -> 3 PM, 10:30 AM stays
    t = re.sub(r"\b(\d+) wks?\b", r"\1 weeks", t)
    t = re.sub(r"\s*&\s*", " and ", t)
    t = re.sub(r"[:;,]\s*\.", ".", t)                                        # "We have:." -> "We have."
    t = re.sub(r"[:;,]\s*$", "", t)
    t = re.sub(r"\.\s*\.", ".", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    if t and t[-1] not in ".?!":
        t += "."
    return t


# ---- Spoken numbers -> digits ("nine eight seven six ..." -> "9876...") ----
_DIGIT_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
                "seven": "7", "eight": "8", "nine": "9", "niner": "9"}
_AMBIGUOUS = {"oh": "0", "o": "0", "to": "2", "too": "2", "for": "4"}   # only count when inside a number
_REPEAT = {"double": 2, "triple": 3}
_TEENS = {"ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14", "fifteen": "15",
          "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19"}
_TENS = {"twenty": "2", "thirty": "3", "forty": "4", "fourty": "4", "fifty": "5", "sixty": "6",
         "seventy": "7", "eighty": "8", "ninety": "9"}
_SEP = re.compile(r"[\s,\-.]+")


def spoken_digits(text: str, min_len: int = 6) -> str:
    """Collapse runs of spoken digits (at least min_len) into a digit string, so phone numbers survive speech-to-text.
    Use a small min_len when the caller is giving a number ('my number is ...'), the default 6 otherwise.
    Short runs ('one course', 'two people') and words like 'to'/'for' around a number are left alone."""
    if not text:
        return text
    tokens = re.findall(r"[A-Za-z]+|\d+|[^A-Za-z\d]+", text)
    out: list[str] = []
    i = 0
    while i < len(tokens):
        parts: list[tuple[int, str, bool]] = []   # (token index, digits, ambiguous)
        j = i
        while j < len(tokens):
            tok, low = tokens[j], tokens[j].lower()
            if tok.isdigit():
                parts.append((j, tok, False))
            elif low in _DIGIT_WORDS:
                parts.append((j, _DIGIT_WORDS[low], False))
            elif low in _TEENS:
                parts.append((j, _TEENS[low], False))
            elif low in _TENS:  # "ninety eight" -> 98, "ninety" alone -> 90 (also "ninety-eight")
                k = j + 1
                while k < len(tokens) and re.fullmatch(r"[\s-]+", tokens[k]):
                    k += 1
                if k < len(tokens) and tokens[k].lower() in _DIGIT_WORDS and _DIGIT_WORDS[tokens[k].lower()] != "0" and k - j <= 2:
                    parts.append((k, _TENS[low] + _DIGIT_WORDS[tokens[k].lower()], False))
                    j = k + 1
                    continue
                parts.append((j, _TENS[low] + "0", False))
            elif low in _AMBIGUOUS and parts:
                parts.append((j, _AMBIGUOUS[low], True))
            elif low in _REPEAT and j + 2 < len(tokens) and tokens[j + 2].lower() in _DIGIT_WORDS:
                parts.append((j + 2, _DIGIT_WORDS[tokens[j + 2].lower()] * _REPEAT[low], False))
                j += 3
                continue
            elif _SEP.fullmatch(tok) and parts:
                pass
            else:
                break
            j += 1
        while parts and parts[-1][2]:          # "...zero to" : the trailing 'to' is a word, not a digit
            parts.pop()
        digits = "".join(d for _, d, _ in parts)
        if len(digits) >= min_len:
            out.append(digits)
            i = parts[-1][0] + 1
        else:
            out.append(tokens[i])
            i += 1
    return "".join(out)


# How speech-to-text tends to hear "DhishaAI" / "Disha": "this AI", "Dishay", "Nishai", "Dish AI", "Disha I" ...
_BRAND = re.compile(
    r"(?<!name is )(?<!i am )(?<!i'm )"                                         # "my name is Disha/Nisha" stays a name
    r"(?:\b(?:dh?(?:i|ee|e)sh(?:aya|ay|ai|e)|dh?(?:i|ee)sha|nish(?:ai|ay)|nisha[\s-]+a\.?\s?i)"   # disha, dishay, dishai, nishai
    r"(?:[\s-]*a\.?\s?i\b)?"                                                   # ... "AI"
    r"|\bdish[\s-]+a\.?\s?i\b"                                                 # "Dish AI"
    r"|\bthis[\s-]+a\.?\s?i\b(?![\s-]*(?:course|courses|programme|program|batch|class))"   # "this AI" (not "this AI course")
    r"|\bthis(?=\W{0,3}\s+i\W*$))"                                             # "about this? I" at the end
    r"(?:\W{0,3}\s+i\W*$)?"                                                    # a stray trailing "I" after the name
    , re.I)
_BARE_THIS = re.compile(r"\b(about|is|know)\s+this\W*$", re.I)


def fix_brand(text: str, first_question: bool = False) -> str:
    """Put the company name back where the recogniser misheard it, so questions about DhishaAI reach the company
    answers instead of 'this AI' course lists. `first_question`: a bare "tell me about this?" at the start of a call
    has nothing else 'this' could mean on a phone, so it is about DhishaAI too."""
    if not text:
        return text
    out = _BRAND.sub(lambda m: "DhishaAI" + ("?" if m.group(0).rstrip().endswith("?") else ""), text)
    if first_question:
        out = _BARE_THIS.sub(lambda m: f"{m.group(1)} DhishaAI?", out)
    return out
