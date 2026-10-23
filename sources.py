"""Recolectores de fuentes públicas.

1. Google News RSS: noticias de rondas, lanzamientos y aceleradoras en LATAM.
2. Directorio público de Y Combinator (dataset abierto yc-oss): startups de LATAM
   hispanohablante en batches recientes.

Ninguna fuente requiere login ni hace scraping de sitios que lo prohíban.
"""
from __future__ import annotations

import calendar
import hashlib
import html
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from . import config

UA = {"User-Agent": "Mozilla/5.0 (latin-leap-scout; +https://github.com)"}
YC_URL = "https://yc-oss.github.io/api/companies/all.json"


@dataclass
class Article:
    id: str
    title: str
    summary: str
    url: str
    source: str
    published: str  # ISO date
    query: str


@dataclass
class YCCompany:
    name: str
    website: str
    location: str
    one_liner: str
    description: str
    batch: str
    team_size: int | None
    yc_url: str
    tags: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _gnews_url(query: str, days: int, edition: tuple[str, str, str]) -> str:
    hl, gl, ceid = edition
    q = urllib.parse.quote(f"{query} when:{days}d")
    return f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"


def parse_feed(content: bytes | str, query: str) -> list[Article]:
    feed = feedparser.parse(content)
    out = []
    for e in feed.entries:
        title = _clean(e.get("title", ""))
        source = _clean(e.get("source", {}).get("title", "")) if e.get("source") else ""
        # Google News añade " - Medio" al final del título
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        published = ""
        if e.get("published_parsed"):
            published = datetime.fromtimestamp(
                calendar.timegm(e.published_parsed), tz=timezone.utc
            ).date().isoformat()
        url = e.get("link", "")
        aid = hashlib.sha1(title.lower().encode()).hexdigest()[:12]
        out.append(Article(
            id=aid, title=title, summary=_clean(e.get("summary", ""))[:400],
            url=url, source=source, published=published, query=query,
        ))
    return out


def fetch_news(days: int) -> list[Article]:
    """Corre todas las consultas y regresa artículos únicos (dedupe por título)."""
    jobs = [(q, config.NEWS_EDITION_ES) for q in config.NEWS_QUERIES_ES]
    jobs += [(q, config.NEWS_EDITION_EN) for q in config.NEWS_QUERIES_EN]
    seen: dict[str, Article] = {}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days + 1)).date().isoformat()
    for query, edition in jobs:
        url = _gnews_url(query, days, edition)
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            arts = parse_feed(r.content, query)
        except Exception as exc:  # una fuente caída no detiene el pipeline
            print(f"  ! Google News falló para '{query}': {exc}")
            continue
        fresh = [a for a in arts if not a.published or a.published >= cutoff]
        for a in fresh:
            seen.setdefault(a.id, a)
        print(f"  · {len(fresh):3d} artículos  ← {query}")
        time.sleep(1)  # cortesía con el servidor
    return list(seen.values())


def _batch_year(batch: str) -> int:
    m = re.search(r"(20\d\d)", batch or "")
    return int(m.group(1)) if m else 0


def fetch_yc(min_year: int) -> list[YCCompany]:
    """Startups activas de YC en LATAM hispanohablante desde `min_year`."""
    try:
        r = requests.get(YC_URL, headers=UA, timeout=60)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        print(f"  ! Directorio YC falló: {exc}")
        return []
    out = []
    for c in data:
        regions = set(c.get("regions") or [])
        if not (regions & config.YC_SPANISH_LATAM):
            continue
        if c.get("status") != "Active" or _batch_year(c.get("batch", "")) < min_year:
            continue
        out.append(YCCompany(
            name=c.get("name", ""), website=c.get("website", ""),
            location=c.get("all_locations", ""), one_liner=c.get("one_liner", ""),
            description=(c.get("long_description") or "")[:1200],
            batch=c.get("batch", ""), team_size=c.get("team_size"),
            yc_url=c.get("url", ""), tags=c.get("tags") or [],
        ))
    print(f"  · {len(out):3d} startups YC en LATAM hispanohablante (batches ≥ {min_year})")
    return out
