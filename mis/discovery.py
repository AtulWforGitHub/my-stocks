"""Universe discovery for 10-15 year compounders that are NOT large caps.
Source: NSE index constituent lists (Nifty Midcap 150 + Nifty Smallcap 250 = ranks ~101-500 by size), then screened.
If the lists cannot be downloaded, a small built-in seed list is used (and the dashboard says so)."""
from __future__ import annotations
import csv
import io
import urllib.request
from pathlib import Path

URLS = {
    "M": ["https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
          "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv"],
    "S": ["https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
          "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv"],
}

# Opinion table: structural industry tailwind 0-5 over 10-15 years. Editable. Matched by keyword on the NSE industry name.
TAILWIND_KEYWORDS = [
    ("defence", 5), ("aerospace", 5), ("railway", 4), ("capital goods", 4), ("power", 4), ("electrical", 4),
    ("electronic", 4), ("construction", 3), ("information technology", 3), ("healthcare", 4), ("pharma", 3),
    ("hospital", 4), ("diagnostic", 4), ("chemical", 3), ("automobile", 3), ("auto component", 4),
    ("financial", 3), ("capital market", 4), ("insurance", 3), ("consumer durables", 4), ("consumer services", 3),
    ("fast moving", 3), ("services", 3), ("realty", 3), ("telecom", 2), ("media", 2), ("textile", 2),
    ("metals", 2), ("oil", 2), ("gas", 2), ("construction materials", 3), ("forest", 2), ("diversified", 2),
]


def tailwind_for(industry: str | None) -> int:
    s = (industry or "").lower()
    for kw, v in TAILWIND_KEYWORDS:
        if kw in s:
            return v
    return 2


def parse_constituents(text: str, cap: str) -> list[dict]:
    out = []
    for r in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        sym = (r.get("Symbol") or "").strip()
        if not sym or sym.upper().startswith("DUMMY") or (r.get("Series") or "EQ").strip() not in ("EQ", ""):
            continue          # NSE index files list DUMMY placeholder symbols that do not trade
        ind = (r.get("Industry") or "Other").strip()
        out.append(dict(ticker=sym + ".NS", name=(r.get("Company Name") or sym).strip(), sector=ind, cap=cap,
                        category="-", tailwind=tailwind_for(ind)))
    return out


def _download(url: str, timeout: int = 25) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (personal research tool)", "Accept": "text/csv,*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None


# Fallback seed (written from memory, unverified): mid/small caps across themes. (ticker, name, sector, cap)
SEED = [
    ("KAYNES.NS", "Kaynes Technology", "Capital Goods", "S"), ("DATAPATTNS.NS", "Data Patterns", "Capital Goods", "S"),
    ("APARINDS.NS", "Apar Industries", "Capital Goods", "S"), ("CDSL.NS", "CDSL", "Financial Services", "S"),
    ("ANANDRATHI.NS", "Anand Rathi Wealth", "Financial Services", "S"), ("CAMS.NS", "CAMS", "Financial Services", "S"),
    ("AFFLE.NS", "Affle India", "Information Technology", "S"), ("NEWGEN.NS", "Newgen Software", "Information Technology", "S"),
    ("INTELLECT.NS", "Intellect Design Arena", "Information Technology", "S"), ("TATAELXSI.NS", "Tata Elxsi", "Information Technology", "M"),
    ("SAFARI.NS", "Safari Industries", "Consumer Durables", "S"), ("FINEORG.NS", "Fine Organic", "Chemicals", "S"),
    ("GALAXYSURF.NS", "Galaxy Surfactants", "Chemicals", "S"), ("CLEAN.NS", "Clean Science", "Chemicals", "S"),
    ("ALKYLAMINE.NS", "Alkyl Amines", "Chemicals", "S"), ("NAVINFLUOR.NS", "Navin Fluorine", "Chemicals", "M"),
    ("SUPREMEIND.NS", "Supreme Industries", "Capital Goods", "M"), ("AMBER.NS", "Amber Enterprises", "Consumer Durables", "M"),
    ("KEC.NS", "KEC International", "Construction", "M"), ("TITAGARH.NS", "Titagarh Rail", "Capital Goods", "S"),
    ("JWL.NS", "Jupiter Wagons", "Capital Goods", "S"), ("COCHINSHIP.NS", "Cochin Shipyard", "Capital Goods", "M"),
    ("GRSE.NS", "Garden Reach Shipbuilders", "Capital Goods", "S"), ("ZENTEC.NS", "Zen Technologies", "Capital Goods", "S"),
    ("ASTRAMICRO.NS", "Astra Microwave", "Capital Goods", "S"), ("PARAS.NS", "Paras Defence", "Capital Goods", "S"),
    ("HBLENGINE.NS", "HBL Engineering", "Capital Goods", "S"), ("GRAVITA.NS", "Gravita India", "Metals & Mining", "S"),
    ("RATNAMANI.NS", "Ratnamani Metals", "Capital Goods", "S"), ("CRAFTSMAN.NS", "Craftsman Automation", "Automobile and Auto Components", "S"),
    ("SANSERA.NS", "Sansera Engineering", "Automobile and Auto Components", "S"), ("ENDURANCE.NS", "Endurance Technologies", "Automobile and Auto Components", "M"),
    ("SUNDRMFAST.NS", "Sundram Fasteners", "Automobile and Auto Components", "M"), ("KIRLOSENG.NS", "Kirloskar Oil Engines", "Capital Goods", "S"),
    ("GRANULES.NS", "Granules India", "Healthcare", "S"), ("ERIS.NS", "Eris Lifesciences", "Healthcare", "S"),
    ("AJANTPHARM.NS", "Ajanta Pharma", "Healthcare", "M"), ("JBCHEPHARM.NS", "JB Chemicals", "Healthcare", "M"),
    ("METROPOLIS.NS", "Metropolis Healthcare", "Healthcare", "S"), ("VIJAYA.NS", "Vijaya Diagnostic", "Healthcare", "S"),
    ("RAINBOW.NS", "Rainbow Children's Medicare", "Healthcare", "S"), ("NATCOPHARM.NS", "Natco Pharma", "Healthcare", "M"),
    ("BIKAJI.NS", "Bikaji Foods", "Fast Moving Consumer Goods", "S"), ("DOMS.NS", "DOMS Industries", "Fast Moving Consumer Goods", "S"),
    ("CAMPUS.NS", "Campus Activewear", "Consumer Durables", "S"), ("METROBRAND.NS", "Metro Brands", "Consumer Services", "S"),
    ("SENCO.NS", "Senco Gold", "Consumer Durables", "S"), ("KAJARIACER.NS", "Kajaria Ceramics", "Consumer Durables", "M"),
    ("CENTURYPLY.NS", "Century Plyboards", "Consumer Durables", "S"), ("FINCABLES.NS", "Finolex Cables", "Capital Goods", "S"),
    ("ELECON.NS", "Elecon Engineering", "Capital Goods", "S"), ("SHAKTIPUMP.NS", "Shakti Pumps", "Capital Goods", "S"),
    ("ANGELONE.NS", "Angel One", "Financial Services", "S"), ("MCX.NS", "Multi Commodity Exchange", "Financial Services", "M"),
    ("CRISIL.NS", "CRISIL", "Financial Services", "S"), ("AAVAS.NS", "Aavas Financiers", "Financial Services", "S"),
    ("HOMEFIRST.NS", "Home First Finance", "Financial Services", "S"), ("CREDITACC.NS", "CreditAccess Grameen", "Financial Services", "S"),
    ("CEATLTD.NS", "CEAT", "Automobile and Auto Components", "S"), ("GABRIEL.NS", "Gabriel India", "Automobile and Auto Components", "S"),
]


def seed_universe() -> list[dict]:
    return [dict(ticker=t, name=n, sector=s, cap=c, category="-", tailwind=tailwind_for(s)) for t, n, s, c in SEED]


def load_universe(state_dir: Path, offline: bool = False) -> tuple[list[dict], str]:
    """Returns (universe, note). Never raises: falls back to cached lists, then to the seed."""
    if offline:
        return seed_universe(), "Offline/demo: built-in seed universe."
    out, notes = [], []
    for cap, urls in URLS.items():
        text, cache = None, state_dir / f"nse_list_{cap}.csv"
        for u in urls:
            text = _download(u)
            if text and "Symbol" in text[:400]:
                cache.write_text(text, encoding="utf-8"); break
            text = None
        if text is None and cache.exists():
            text = cache.read_text(encoding="utf-8"); notes.append(f"{'Midcap 150' if cap=='M' else 'Smallcap 250'}: used saved copy (download failed).")
        if text:
            out += parse_constituents(text, cap)
    if len(out) < 150:
        return seed_universe(), "Could not download the NSE Midcap/Smallcap lists; using the built-in seed list (about 60 names)."
    seen, uniq = set(), []
    for u in out:
        if u["ticker"] not in seen:
            seen.add(u["ticker"]); uniq.append(u)
    return uniq, "; ".join(notes) or f"NSE Midcap 150 + Smallcap 250 lists ({len(uniq)} companies)."


def prefilter(universe: list[dict], funds: dict[str, dict], ucfg: dict) -> list[dict]:
    """Cheap fundamental screen on cached info. Returns shortlist (best first) with a preliminary score."""
    lo, hi = ucfg["min_mcap_cr"], ucfg["max_mcap_cr"]
    out = []
    for u in universe:
        f = funds.get(u["ticker"])
        if not f or not f.get("available"):
            continue
        mc = f.get("market_cap_cr")
        if mc is None or not (lo <= mc <= hi):
            continue
        roe, de, rg, eg = f.get("roe"), f.get("debt_to_equity"), f.get("rev_growth"), f.get("earn_growth")
        fin = f.get("is_financial", False)
        if roe is not None and roe < 0.10:
            continue
        if de is not None and not fin and de > 1.5:
            continue
        if rg is not None and rg < -0.05:
            continue
        cl = lambda x: max(0.0, min(1.0, x))  # noqa: E731
        pre = 0.4 * cl((roe or 0.10) / 0.25) + 0.35 * cl(max(eg or 0, rg or 0) / 0.30) + 0.25 * (1 - cl((0 if (de is None or fin) else de) / 1.5))
        out.append({**u, "prelim": round(pre, 4)})
    out.sort(key=lambda x: x["prelim"], reverse=True)
    return out[: ucfg["shortlist_size"]]
