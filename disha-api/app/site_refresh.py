"""Nightly website refresh: re-read dhishaai.com and rebuild Disha's company knowledge from the live pages.

- Fetches WEBSITE_PAGES (plus up to 10 blog/batch pages linked from Insights) with a plain HTTP GET.
- Keeps only readable text (no scripts, menus, forms), splits it into sections by heading, and saves everything
  to data/website_kb.json. get_company_info() searches this file first; app/knowledge.py is the fallback.
- A page that fails or comes back nearly empty keeps its previous copy, so a bad night never wipes knowledge.
- Also reads the website programmes' durations and next-batch dates and stores them as course updates.

Run now:   POST /admin/refresh-website   (console token)   or   python -m app.site_refresh
Status:    GET  /admin/website-status
"""
from __future__ import annotations

import json
import logging
import re
import threading
from collections import Counter
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from .config import settings

log = logging.getLogger(__name__)
KB_FILE = Path(__file__).resolve().parent.parent / "data" / "website_kb.json"
_lock = threading.Lock()

_SKIP = {"script", "style", "noscript", "svg", "form", "select", "option", "textarea", "button", "iframe", "head", "template"}
_BLOCK = {"p", "div", "li", "br", "tr", "td", "th", "section", "article", "header", "footer", "nav", "ul", "ol",
          "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "figcaption", "span"}
_HEAD = {"h1", "h2", "h3", "h4"}
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"


class _Text(HTMLParser):
    """Collects (kind, text) lines: kind 'h' for headings, 't' for text. Also collects links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[tuple[str, str]] = []
        self.links: list[str] = []
        self.title = ""
        self._skip = 0
        self._buf: list[str] = []
        self._kind = "t"
        self._in_title = False

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if text:
            self.lines.append((self._kind, text))
        self._buf, self._kind = [], "t"

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in _SKIP:
            self._skip += 1
            return
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in _BLOCK:
            self._flush()
            if tag in _HEAD:
                self._kind = "h"

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if tag in _BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if not self._skip:
            self._buf.append(data)

    def close(self):
        super().close()
        self._flush()


def _parse(html: str) -> _Text:
    p = _Text()
    p.feed(html)
    p.close()
    return p


def _page_name(url: str, title: str) -> str:
    t = re.split(r"\s[-|–]\s", title.strip())[0].strip()
    if t and t.lower() not in ("dhishaai complete analytics", "home"):
        return t
    path = urlparse(url).path.strip("/")
    return path.split("/")[-1].replace("-", " ").replace("_", " ").title() if path else "Home"


def _chunks(lines: list[tuple[str, str]], boiler: set[str]) -> list[dict]:
    """Group text lines under their nearest heading; ~900 characters per chunk."""
    out, heading, buf = [], "", []

    def emit():
        text = " ".join(buf).strip()
        if len(text) > 25:
            for i in range(0, len(text), 900):
                out.append({"heading": heading, "text": text[i:i + 900]})

    for kind, text in lines:
        if text in boiler:
            continue
        if kind == "h":
            emit()
            heading, buf = text, []
        else:
            if not buf or buf[-1] != text:
                buf.append(text)
    emit()
    return out


def _fetch(client: httpx.Client, url: str) -> str | None:
    try:
        r = client.get(url)
        if r.status_code == 200 and "html" in r.headers.get("content-type", "html"):
            return r.text
        log.warning("website refresh: %s returned %s", url, r.status_code)
    except Exception as e:
        log.warning("website refresh: %s failed (%s)", url, type(e).__name__)
    return None


_SKIP_URL = re.compile(r"/(tag|category|author|feed|page|wp-json|wp-admin|cart|checkout|my-account)/|\?|#|"
                   r"\.(jpe?g|png|gif|webp|svg|pdf|mp4|zip|css|js|xml)$", re.I)


def discover_pages(client: httpx.Client, base: str, limit: int) -> list[str]:
    """Every page the website lists in its sitemap (WordPress core, Yoast, RankMath, or a plain sitemap.xml),
    so a page added to the site is picked up on the next refresh without any configuration."""
    host = urlparse(base).netloc
    found: list[str] = []

    def locs(xml: str) -> list[str]:
        return [u.strip() for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml, re.I | re.S)]

    for name in ("wp-sitemap.xml", "sitemap_index.xml", "sitemap.xml", "sitemap-index.xml"):
        try:
            r = client.get(f"{base}/{name}")
        except Exception:
            continue
        if r.status_code != 200 or "<loc>" not in r.text:
            continue
        entries = locs(r.text)
        children = [u for u in entries if u.lower().endswith(".xml")]
        pages = [u for u in entries if not u.lower().endswith(".xml")]
        for child in children[:12]:
            if re.search(r"(tag|category|author|user|taxonom)", child, re.I):
                continue
            try:
                rc = client.get(child)
                if rc.status_code == 200:
                    pages += [u for u in locs(rc.text) if not u.lower().endswith(".xml")]
            except Exception:
                continue
        for u in pages:
            if urlparse(u).netloc == host and not _SKIP_URL.search(u) and u not in found:
                found.append(u)
        if found:
            log.info("website refresh: sitemap %s lists %s pages", name, len(found))
            break
    return found[:limit]


def load() -> dict:
    try:
        return json.loads(KB_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _course_updates(all_text: str) -> dict:
    """Durations and next-batch dates of the website programmes, read from the page text."""
    from .knowledge import COURSES
    updates = {}
    names = {"agentic-ai": ["Agentic AI"], "data-science": ["Data Science"], "data-analytics": ["Data Analytics"],
             "excel-pro": ["Excel Pro+", "Excel Pro"]}
    for c in COURSES:
        upd = {}
        for name in names.get(c["id"], [c["name"]]):
            for m in re.finditer(re.escape(name), all_text, re.I):
                window = all_text[m.end(): m.end() + 160]
                d = re.search(r"Duration\s*:?\s*(\d+(?:\.\d+)?\s*(?:months?|weeks?|days?))", window, re.I) \
                    or re.match(r"[^.]{0,40}?\b(\d+(?:\.\d+)?\s*(?:months?|weeks?|days?))\b", window, re.I)
                if d and "duration" not in upd:
                    upd["duration"] = re.sub(r"\s+", " ", d.group(1)).strip()
                around = all_text[max(0, m.start() - 120): m.end() + 160]
                b = re.search(r"batch[^.]{0,60}?(\d{1,2})(?:st|nd|rd|th)?[\s-]+(" + _MONTHS + r")[a-z]*[\s,-]+(\d{4})", around, re.I)
                if b:
                    try:
                        when = datetime.strptime(f"{b.group(1)} {b.group(2)[:3]} {b.group(3)}", "%d %b %Y").date()
                        if when >= date.today() and ("next_batch" not in upd or when < date.fromisoformat(upd["next_batch"])):
                            upd["next_batch"] = when.isoformat()
                    except ValueError:
                        pass
        if upd:
            updates[c["id"]] = upd
    return updates


def refresh(pages: list[str] | None = None) -> dict:
    """Fetch the website and rebuild data/website_kb.json. Returns a short report."""
    with _lock:
        base = settings.website_url.rstrip("/")
        paths = pages or [p.strip() for p in settings.website_pages.split(",") if p.strip()]
        urls = [urljoin(base + "/", p.lstrip("/")) for p in paths]
        old = load()
        old_pages = {p["url"]: p for p in old.get("pages", [])}
        fetched: dict[str, _Text] = {}
        headers = {"User-Agent": "DishaFrontDesk/1.0 (+website knowledge refresh)"}
        with httpx.Client(timeout=settings.website_timeout_seconds, follow_redirects=True, headers=headers) as client:
            if pages is None:  # the whole site, as its sitemap lists it (new pages appear here automatically)
                for u in discover_pages(client, base, settings.website_max_pages):
                    if u.rstrip("/") not in {x.rstrip("/") for x in urls}:
                        urls.append(u)
                urls = urls[:settings.website_max_pages]
            for url in urls:
                html = _fetch(client, url)
                if html:
                    fetched[url] = _parse(html)
            # blog / batch pages linked from Insights (same site, .html uploads or /insights/... posts), at most 10
            extra = []
            for url, page in list(fetched.items()):
                if "insight" not in url:
                    continue
                for href in page.links:
                    full = urljoin(url, href)
                    if urlparse(full).netloc == urlparse(base).netloc and full not in urls and full not in extra and \
                            (full.endswith(".html") or "/20" in urlparse(full).path):
                        extra.append(full)
            for url in extra[:10]:
                html = _fetch(client, url)
                if html:
                    fetched[url] = _parse(html)

        # lines on most pages are header/footer boilerplate: keep them once, as their own section
        counts = Counter()
        for page in fetched.values():
            counts.update({t for _, t in page.lines})
        min_pages = max(3, int(len(fetched) * 0.6))
        boiler = {t for t, n in counts.items() if n >= min_pages}

        pages_out, ok, kept, failed = [], [], [], []
        for url in urls + extra[:10]:
            page = fetched.get(url)
            chunks = _chunks(page.lines, boiler) if page else []
            if page and sum(len(c["text"]) for c in chunks) >= 20:
                pages_out.append({"url": url, "name": _page_name(url, page.title), "chunks": chunks,
                                  "fetched_at": datetime.now().isoformat(timespec="seconds")})
                ok.append(url)
            elif url in old_pages:
                pages_out.append(old_pages[url])
                kept.append(url)
            else:
                failed.append(url)
        if boiler:
            site_wide = [t for t, _ in counts.most_common() if t in boiler]
            pages_out.append({"url": base + "/#site-wide", "name": "Site-wide (header and footer)",
                              "chunks": [{"heading": "Contact and links", "text": " | ".join(site_wide)[:1800]}],
                              "fetched_at": datetime.now().isoformat(timespec="seconds")})
        elif old_pages.get(base + "/#site-wide"):
            pages_out.append(old_pages[base + "/#site-wide"])

        if not ok:  # nothing fetched at all: keep the previous file untouched
            report = {"ok": False, "error": "no page could be fetched; previous knowledge kept",
                      "failed": failed, "last_good": old.get("refreshed_at")}
            log.warning("website refresh failed: %s", report["error"])
            return report

        all_text = " ".join(f"{c['heading']}. {c['text']}" for p in pages_out for c in p["chunks"])
        course_updates = _course_updates(all_text) or old.get("course_updates", {})
        data = {"source": base, "refreshed_at": datetime.now().isoformat(timespec="seconds"),
                "pages": pages_out, "course_updates": course_updates}
        KB_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = KB_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(KB_FILE)
        _apply_course_updates()
        report = {"ok": True, "refreshed_at": data["refreshed_at"], "pages_updated": len(ok),
                  "pages_kept_from_last_time": kept, "pages_failed": failed,
                  "sections": sum(len(p["chunks"]) for p in pages_out), "course_updates": course_updates}
        log.info("website refresh: %s pages updated, %s kept, %s failed", len(ok), len(kept), len(failed))
        return report


def _apply_course_updates() -> None:
    from .db import SessionLocal
    from .knowledge import apply_website_courses
    db = SessionLocal()
    try:
        apply_website_courses(db)
    except Exception:
        log.exception("could not apply course updates from the website")
    finally:
        db.close()


# ---- search over the refreshed pages ----
_STOP = set("a an the is are was were be to of in on for and or with at by from as it its this that what which who whom "
            "how when where do does did can could would will you your we our us i me my about tell please any there "
            "have has had give know want".split())


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9+]+", text.lower()) if w not in _STOP and len(w) > 1]


def search(question: str, extra_terms: list[str] | None = None, top: int = 4) -> list[dict]:
    data = load()
    pages = data.get("pages") or []
    if not pages:
        return []
    chunks = [(p, c) for p in pages for c in p["chunks"]]
    def label(p):  # page title plus its URL words ("careers", "about us"), so a vague page title still matches
        return f"{p['name']} {urlparse(p['url']).path.replace('/', ' ').replace('-', ' ')}"
    docs = [Counter(_tokens(f"{label(p)} {c['heading']} {c['text']}")) for p, c in chunks]
    n = len(docs)
    df = Counter(t for d in docs for t in d)
    q = _tokens(question) + [t for term in (extra_terms or []) for t in _tokens(term)]
    if not q:
        return []
    import math
    scored = []
    for (p, c), d in zip(chunks, docs):
        s = 0.0
        for t in set(q):
            if t in d:
                s += math.log(1 + n / df[t]) * (1 + 0.3 * min(d[t], 3))
            if t in _tokens(c["heading"] + " " + label(p)):
                s += 1.0
        if p["name"].startswith("Site-wide"):
            s *= 0.4  # the menu/footer mentions everything; prefer the real page
        if s > 0:
            scored.append((s, p, c))
    scored.sort(key=lambda x: -x[0])
    return [{"topic": f"{p['name']} - {c['heading']}".strip(" -"), "info": c["text"], "url": p["url"]}
            for _, p, c in scored[:top]]


def page_digest(slug: str, must: str, each: int = 260) -> str:
    """All chunks of one live page whose text matches `must`, joined into one answer: every founder from About Us,
    every job from Careers. (search() returns only the top few chunks, which can leave one out.)"""
    for p in load().get("pages") or []:
        if (urlparse(p["url"]).path.strip("/").split("/")[-1] or "home") == slug:
            parts = [f"{c['heading']}: {c['text'][:each].rsplit(' ', 1)[0]}" for c in p["chunks"]
                     if re.search(must, c["text"], re.I)]
            return " | ".join(parts)
    return ""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(refresh(), indent=1, default=str))
