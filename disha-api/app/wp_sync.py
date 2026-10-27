"""Pull courses from WordPress (custom post type `course` exposed over the REST API) into the
courses table, so marketing edits them in WordPress and Disha picks them up within minutes."""
from __future__ import annotations

import logging
from datetime import date

import httpx
from sqlalchemy import select

from .config import settings
from .db import Course, SessionLocal

log = logging.getLogger(__name__)


def fetch_wp_courses() -> list[dict]:
    url = f"{settings.wp_base_url.rstrip('/')}/wp-json/wp/v2/course"
    r = httpx.get(url, params={"per_page": 100, "status": "publish"}, timeout=20)
    r.raise_for_status()
    out = []
    for post in r.json():
        meta = post.get("meta", {}) or {}
        try:
            next_batch = date.fromisoformat(str(meta.get("disha_next_batch") or "")[:10])
        except ValueError:
            next_batch = date.today()
        out.append({
            "id": post.get("slug") or str(post["id"]),
            "name": _strip(post.get("title", {}).get("rendered", "")),
            "track": meta.get("disha_track") or "",
            "fee_inr": int(float(meta.get("disha_fee") or 0)),
            "duration_weeks": int(float(meta.get("disha_duration_weeks") or 0)),
            "mode": meta.get("disha_mode") or "",
            "next_batch": next_batch,
            "suited_for": meta.get("disha_suited_for") or _strip(post.get("excerpt", {}).get("rendered", "")),
            "brochure_url": meta.get("disha_brochure_url") or "",
        })
    return out


def _strip(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html or "").replace("&amp;", "&").replace("&#8211;", "-").strip()


def sync_courses() -> int:
    """Upsert WordPress courses into the courses table. Returns the number synced. No-op without WP_BASE_URL."""
    if not settings.wp_base_url:
        return 0
    try:
        rows = fetch_wp_courses()
    except Exception as e:
        log.warning("WordPress course sync failed: %s", e)
        return 0
    db = SessionLocal()
    try:
        seen = set()
        for r in rows:
            seen.add(r["id"])
            c = db.get(Course, r["id"])
            if c is None:
                db.add(Course(**r))
            else:
                for k, v in r.items():
                    setattr(c, k, v)
        # courses removed in WordPress disappear here too, unless they still have appointments referencing them
        for c in db.scalars(select(Course)).all():
            if c.id not in seen and settings.wp_base_url:
                try:
                    db.delete(c)
                except Exception:
                    pass
        db.commit()
        log.info("synced %d courses from WordPress", len(rows))
        return len(rows)
    finally:
        db.close()
