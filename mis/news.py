"""Headlines from Google News RSS. They are UNVERIFIED third-party text: shown with source, link and time, de-duplicated,
never summarised into a price view, and never allowed to trigger a trade. Risk-keyword hits only raise a 'read this' item."""
from __future__ import annotations
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

RISK_WORDS = re.compile(r"\b(fraud|raid|probe|sebi|resign|resigns|downgrade|insolvency|default|penalty|ed |cbi|pledge|auditor|scam|"
                        r"halt|suspend|bankrupt|show.?cause|investigation|short seller|hindenburg)\b", re.I)


def safe_url(u: str | None) -> str | None:
    """Only plain http(s) links from an untrusted feed are kept (never javascript:, data:, file: ...)."""
    u = (u or "").strip()
    return u if re.match(r"^https?://", u, re.I) else None


_GENERIC = {"the", "india", "indian", "bharat", "national", "limited", "ltd", "company", "co", "corporation", "corp", "industries", "industry", "global",
            "international", "enterprises", "holdings", "group", "services", "technologies", "technology", "systems", "finance", "financial", "bank", "power"}


def key_word(company: str) -> str | None:
    """The distinctive first word of a company name (for example 'Ajanta' in 'Ajanta Pharmaceuticals Ltd.')."""
    for w in re.findall(r"[A-Za-z0-9&]+", company or ""):
        if len(w) >= 4 and w.lower() not in _GENERIC:
            return w.lower()
    return None


def relevant(title: str, company: str) -> bool:
    """A search for a company name returns loosely related articles. Keep only headlines that actually name the company."""
    k = key_word(company)
    return bool(k) and re.search(r"\b" + re.escape(k), title or "", re.I) is not None


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", t.lower())[:70]


def fetch(query: str, limit: int = 3, timeout: int = 15) -> list[dict]:
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query + " when:3d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 personal-research"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            root = ET.fromstring(r.read())
    except Exception:  # noqa: BLE001
        return []
    out = []
    for it in root.iter("item"):
        try:
            ts = parsedate_to_datetime(it.findtext("pubDate")).isoformat(timespec="minutes")
        except Exception:  # noqa: BLE001
            ts = None
        src = it.find("source")
        title = (it.findtext("title") or "").strip()
        out.append(dict(title=title, url=safe_url(it.findtext("link")), published=ts, source=src.text if src is not None else "unknown",
                        risk=bool(RISK_WORDS.search(title)), status="unverified headline"))
        if len(out) >= limit:
            break
    return out


def dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for i in items:
        k = _norm(i["title"])
        if k and k not in seen:
            seen.add(k); out.append(i)
    return out


def contradictory(items: list[dict]) -> bool:
    """Crude flag: both 'surge/gain' and 'fall/slump' style headlines for the same company in one batch."""
    up = any(re.search(r"\b(surge|jump|rally|soar|gain)", i["title"], re.I) for i in items)
    dn = any(re.search(r"\b(fall|slump|plunge|tumble|drop|crash)", i["title"], re.I) for i in items)
    return up and dn
