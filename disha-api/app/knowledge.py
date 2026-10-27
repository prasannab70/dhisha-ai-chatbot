"""Company knowledge: Disha answers company questions ONLY from the live copy of the website (WEBSITE_URL),
which app/site_refresh.py downloads on start and every few hours. Nothing about the company is written here;
when the website changes, Disha's answers change with it.

COURSES below are the learning programmes as the website lists them (added to the course table alongside the
courses entered by hand); their duration and next-batch dates are updated from the website too.
"""
from __future__ import annotations

import re
from datetime import date

from .config import settings

WEBSITE = settings.website_url.rstrip("/")

# ---- The four learning programmes as the website lists them (no fees, timings or mode are published).
#      They are ADDED to the existing course list; nothing existing is removed or changed. ----
NOT_ANNOUNCED = date(1900, 1, 1)  # stored when the website gives no batch date
COURSES = [
    {"id": "agentic-ai", "name": "Agentic AI and AI Agents", "track": "AI & GenAI", "duration": "2 months",
     "next_batch": date(2026, 10, 24),
     "suited_for": "People with basic Python who want to build AI agents and AI automation",
     "details": ("Build intelligent AI agents with LLMs, RAG, LangGraph, multi-agent systems and enterprise AI workflows. "
                 "Hands-on real-world projects, tool integrations and a capstone. 11 modules and 3 portfolio projects: "
                 "Foundations (Python, deep-learning basics, Transformers); Pydantic data modelling; LangChain and a first RAG app "
                 "(FAISS, Chroma); Groq, LCEL and deployment (FastAPI, LangServe, Streamlit); modern LangChain v1 agents and tool calling; "
                 "LangGraph basics; LangGraph agent patterns (ReAct, routing, streaming); agentic workflow design; RAG with LangGraph "
                 "and guardrails; multi-agent systems in LangGraph, Google ADK and OpenAI Agents SDK; optional fine-tuning (LoRA, QLoRA) "
                 "and Model Context Protocol (MCP). Projects: Telecom Customer Intelligence, AI Business Report Generator, "
                 "MySQL Automation with two agents. Prerequisite: basic Python. Outcome: industry-ready AI automation skills.")},
    {"id": "data-science", "name": "Data Science", "track": "Programming & Data Science", "duration": "4 months",
     "next_batch": NOT_ANNOUNCED,
     "suited_for": "Those aiming to become data scientists",
     "details": ("Python, Machine Learning, Deep Learning, Time Series Forecasting, Statistics and AI fundamentals. "
                 "Hands-on projects, industry case studies and a capstone project. Outcome: industry-ready data scientist.")},
    {"id": "data-analytics", "name": "Data Analytics", "track": "Analytics & BI", "duration": "3.5 months",
     "next_batch": NOT_ANNOUNCED,
     "suited_for": "Those aiming for data analyst and analytics jobs",
     "details": ("SQL, Power BI, Python, Statistics and AI fundamentals. Real-world projects, case studies, capstone projects "
                 "and placement-focused mentorship. Outcome: job-ready analytics skills.")},
    {"id": "excel-pro", "name": "Excel Pro+", "track": "Analytics & BI", "duration": "2 days",
     "next_batch": NOT_ANNOUNCED,
     "suited_for": "Professionals who work with Excel and reporting",
     "details": ("XLOOKUP, LAMBDA, Python in Excel, Power Query, Power Pivot, AI-powered Excel and interactive dashboards, "
                 "with practical projects. Outcome: workflow automation, efficient data analysis and industry-ready reporting.")},
]

# ---- Topics: which words in a question point at which website page. Only routing lives here; every fact
#      comes from the live copy of the website (data/website_kb.json, refreshed by app/site_refresh.py). ----
TOPICS: list[tuple[str, tuple[str, ...], str]] = [
    ("About DhishaAI", ("about", "company", "who are", "what is dhishaai", "what do you do", "story", "overview", "dhishaai"), "/about-us/"),
    ("Vision and mission", ("vision", "mission", "goal", "purpose", "aim"), "/about-us/"),
    ("Core values", ("value", "values", "culture", "principle"), "/about-us/"),
    ("Why choose DhishaAI", ("why", "choose", "different", "differentiator", "better", "advantage"), "/about-us/"),
    ("Leadership / founders", ("founder", "found", "started", "leadership", "who runs", "who owns", "ceo", "cto", "cdo", "caio",
                              "director", "owner", "team", "deepak", "triveni", "bhimanagouda", "ravi", "management", "head",
                              "chief"), "/about-us/"),
    ("Services overview", ("service", "services", "offer", "what do you provide", "pillar", "vertical"), "/services/"),
    ("Learning & Development / training", ("training", "learning", "upskill", "corporate training", "college", "course", "courses",
                                           "programme", "program", "workshop", "bootcamp", "internship programme"), "/learning-development/"),
    ("Product Development", ("product development", "develop", "build", "software", "app", "website development", "erp", "crm",
                             "mobile app", "saas"), "/product-development/"),
    ("Project Consulting", ("consulting", "consultancy", "consultant", "strategy", "roadmap", "analysis", "transformation",
                            "dashboard", "analytics project"), "/project-consulting/"),
    ("Resource Management / staffing", ("resource", "staffing", "hire", "hiring", "talent", "manpower", "outsourc", "deploy"), "/resource-management/"),
    ("Products", ("product", "products", "timelens", "time lens", "lms", "forecast", "demo of product"), "/products/"),
    ("Industries", ("industry", "industries", "sector", "domain", "retail", "oil", "gas", "manufacturing", "automotive",
                    "healthcare", "pharma", "bfsi", "bank", "telecom", "fmcg"), "/industries/"),
    ("Clients", ("client", "clients", "customer", "partner", "worked with", "companies"), "/"),
    ("Reviews / testimonials", ("review", "reviews", "rating", "testimonial", "testimonies", "testimony", "feedback", "google"), "/testimonials/"),
    ("Careers / jobs / internships", ("career", "careers", "carrier", "job", "jobs", "opening", "vacanc", "intern", "internship",
                                      "apply", "work at", "recruit", "hiring"), "/careers/"),
    ("Upcoming batch / news", ("batch", "new batch", "starting", "start date", "upcoming", "news", "blog", "insight", "agentic"), "/insights/"),
    ("Contact", ("contact", "phone", "call", "number", "email", "mail", "whatsapp", "reach you", "social", "linkedin", "office",
                 "where", "address", "location", "located", "visit", "hours", "timings", "opening hours", "branch",
                 "instagram", "youtube", "facebook", "twitter"), "/contact/"),
]
NOT_LOADED = ("The website copy has not been loaded yet. Say you will check and offer a counsellor or a callback; "
              "an administrator can load it with POST /admin/refresh-website.")


def _course_line(c: dict) -> str:
    batch = c["next_batch"].strftime("%d %B %Y") if c["next_batch"] != NOT_ANNOUNCED else "not announced"
    return f"{c['name']} ({c['duration']}; next batch: {batch}): {c['details']}"


def _topics(t: str) -> list[tuple[float, str, str]]:
    """(score, title, page) for every topic whose keywords appear in the question, best first."""
    scored = []
    for title, keys, page in TOPICS:
        weight = 0.4 if title == "About DhishaAI" else 1.0   # generic words ('about', 'dhishaai') must not outrank specific topics
        score = weight * sum(1 for k in keys if re.search(r"\b" + re.escape(k), t))
        if score:
            scored.append((score, title, page))
    scored.sort(key=lambda x: -x[0])
    return scored


def get_company_info(topic: str = "") -> dict:
    """Best-matching sections of the live website copy for a question about DhishaAI."""
    from . import site_refresh
    t = (topic or "").lower()
    topics = _topics(t)
    course_q = any(w in t for w in ("course", "agentic", "programme", "program", "batch", "training", "fee", "duration"))
    data = site_refresh.load()
    if not data.get("pages"):
        return {"source": WEBSITE, "results": [], "note": NOT_LOADED}
    extra = [topics[0][1]] + [w for w in topics[0][2].strip("/").split("-") if w] if topics else []
    picked = list(site_refresh.search(topic or "about DhishaAI", extra_terms=extra, top=4))
    # whole-list topics: every founder / every open job, not just the top-scoring few chunks
    top_titles = [x[1] for x in topics[:2]]
    if "Leadership / founders" in top_titles:
        allf = site_refresh.page_digest("about-us", r"\bfounder\b", each=200)
        if allf:
            picked.insert(0, {"topic": "All founders (About Us page)", "info": allf})
    if "Careers / jobs / internships" in top_titles:
        jobs = site_refresh.page_digest("careers", r"Location:", each=120)
        if jobs:
            picked.insert(0, {"topic": "Current job openings (Careers page)",
                              "info": jobs + " | How to apply: through the Careers page on the website, or share your "
                                             "resume there to join the talent pool."})
    if not picked:  # nothing specific matched: the About page is the best general answer
        about = site_refresh.page_digest("about-us", r".", each=400) or site_refresh.page_digest("home", r".", each=400)
        if about:
            picked.append({"topic": "About DhishaAI (overview)", "info": about[:1500]})
    if course_q or any(p["topic"].startswith("Learning") for p in picked):
        picked.append({"topic": "Programme details", "info": " | ".join(_course_line(c) for c in courses_now())})
    source = f"{data.get('source', WEBSITE)} (live website, refreshed {data.get('refreshed_at', '?')[:16].replace('T', ' ')})"
    return {"source": source, "results": picked,
            "note": "Answer only from these results. If the answer is not here, say the website does not mention it and "
                    "offer a counsellor or callback."}


def facts_for(question: str) -> str:
    """Website facts to hand the model directly when a question is clearly about the company (founders, services,
    careers, ...), so the answer does not depend on the model remembering to call get_company_info."""
    t = (question or "").lower()
    hits = [x for x in _topics(t)
            if (x[1] != "About DhishaAI" or re.search(r"\b(dhishaai|company|who are you|what do you do)\b", t))
            # course lists and batches come from get_courses (all courses), not from the website summary
            and (not x[1].startswith(("Learning", "Upcoming")) or re.search(r"\b(corporate|college|company training|for (my )?team)\b", t))]
    if not hits:
        return ""
    info = get_company_info(question)
    if not info["results"]:
        return ""
    lines = [f"- {r['topic']}: {r['info'][:1200]}" for r in info["results"][:4]]
    return "WEBSITE FACTS FOR THIS QUESTION (from " + info["source"] + "; answer from these):\n" + "\n".join(lines)


def courses_now() -> list[dict]:
    """COURSES with any duration / next-batch changes picked up by the nightly website refresh."""
    from . import site_refresh
    updates = site_refresh.load().get("course_updates", {})
    out = []
    for c in COURSES:
        c = dict(c)
        u = updates.get(c["id"], {})
        if u.get("duration"):
            c["duration"] = u["duration"]
        if u.get("next_batch"):
            try:
                c["next_batch"] = date.fromisoformat(u["next_batch"])
            except ValueError:
                pass
        out.append(c)
    return out


def apply_website_courses(db) -> int:
    """ADD the website's programmes to the course list. Existing courses are kept as they are (and any that an
    earlier version hid are shown again)."""
    from .db import Course
    for c in db.query(Course).all():
        if c.active is False:
            c.active = True
    for x in courses_now():
        row = db.get(Course, x["id"]) or Course(id=x["id"])
        row.name, row.track, row.fee_inr = x["name"], x["track"], 0
        row.duration_weeks, row.duration_text = 0, x["duration"]
        row.mode, row.next_batch = "", x["next_batch"]
        row.suited_for, row.details, row.active = x["suited_for"], x["details"], True
        db.add(row)
    db.commit()
    return len(COURSES)
