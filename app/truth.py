"""TRUE pillar: does this shot contradict what the narration claims?

    claims   = extract_claims("Heavy rain lashed Mumbai today.")     # place, time, weather (EN + Hindi)
    evidence = what we know about the shot (GPS, signboard OCR, stock title/tags, recorded date, weather tag)
    verdict  = verdict(claims, facts)  ->  status ok | unverified | warn | bad  + evidence strings + label

Principles (decision D21):
  * a wrong PLACE is never acceptable -> `bad` (excluded from the plan), but only on hard evidence
    (GPS / OCR text / stock title) that names a different place;
  * an OLD date is acceptable when labelled -> `warn` + auto label `FILE · <year>`;
  * missing evidence is never a contradiction -> `unverified` (neutral);
  * weather is a soft visual signal -> `bad` only at very high confidence.
Everything is derived on the fly from stored facts, so improving the gazetteer needs no re-index.
"""
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache

from . import db
from .config import RESOURCES

RECENT_DAYS = 45                 # "today / this week" tolerates footage up to this old
# Calibration (2026-10-02, contact-sheet check of 1,881 shots): zero-shot weather is ~85-90% precise at 0.90, so it is
# only allowed to EXCLUDE a shot at 0.97; below that it can only warn.
WEATHER_BAD_CONF = 0.97
WEATHER_WARN_CONF = 0.80
GPS_MAX_KM = 60.0
DELTA_OK_PLACE, DELTA_OK_OTHER, DELTA_WARN, DELTA_CAP = 0.030, 0.010, -0.010, 0.050


# ───────────────────────────── gazetteer ─────────────────────────────
@lru_cache(maxsize=1)
def _gaz():
    entries = json.load(open(RESOURCES / "gazetteer.json", encoding="utf-8"))
    by_name = {e["name"]: e for e in entries}
    latin, deva = [], []
    for e in entries:
        for a in e["aliases"]:
            a_l = a.lower()
            (deva if re.search(r"[ऀ-ॿ]", a) else latin).append((a_l, e["name"]))
    latin.sort(key=lambda x: -len(x[0]))
    deva.sort(key=lambda x: -len(x[0]))
    pats = [(a, n, re.compile(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])")) for a, n in latin]
    return by_name, pats, deva


def entry(name):
    return _gaz()[0].get(name)


def is_within(a: str, b: str) -> bool:
    """True if place a is inside (or equal to) place b: Mumbai within Maharashtra within India."""
    by = _gaz()[0]
    seen = 0
    while a and seen < 6:
        if a == b:
            return True
        a = (by.get(a) or {}).get("parent")
        seen += 1
    return False


def related(a: str, b: str) -> bool:
    return is_within(a, b) or is_within(b, a)


def match_places(text: str) -> list:
    """-> [(canonical name, matched alias)] in order of first mention. Tolerates OCR that drops spaces
    ('DelhiMetro') for aliases of 5+ letters."""
    if not text:
        return []
    by, pats, deva = _gaz()
    t = text.lower()
    nospace = re.sub(r"[^a-z0-9]", "", t)
    found = {}
    for a, name, rx in pats:
        if a not in t and not (len(a) >= 5 and re.sub(r"[^a-z0-9]", "", a) in nospace):
            continue
        m = rx.search(t)
        if m:
            found.setdefault(name, (m.start(), a))
        elif len(a) >= 5 and re.sub(r"[^a-z0-9]", "", a) in nospace:
            found.setdefault(name, (10**6 + len(found), a))
    for a, name in deva:
        i = t.find(a)
        if i >= 0:
            found.setdefault(name, (i, a))
    return [(n, al) for n, (_, al) in sorted(found.items(), key=lambda kv: kv[1][0])]


def nearest_city(lat, lon, max_km=GPS_MAX_KM):
    best = None
    for e in _gaz()[0].values():
        if e.get("kind") != "city" or "lat" not in e:
            continue
        d = _haversine(lat, lon, e["lat"], e["lon"])
        if d <= max_km and (best is None or d < best[1]):
            best = (e["name"], d)
    return best


def _haversine(la1, lo1, la2, lo2):
    p1, p2 = math.radians(la1), math.radians(la2)
    dphi, dl = p2 - p1, math.radians(lo2 - lo1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


# ───────────────────────────── claims ─────────────────────────────
_RECENT = re.compile(
    r"\b(today|tonight|this (?:morning|afternoon|evening|week|weekend|month)|yesterday|last night|right now|"
    r"currently|just now|breaking|latest|these days|at the moment)\b|आज|आजकल|अभी|इस हफ्ते|इस सप्ताह|इस महीने|ताज़ा|कल रात|बीती रात")
_YEAR = re.compile(r"(?:(?:in|during|since|from|of|year|circa|c\.|back in)\s+|^|[.!?]\s*|\()((?:19|20)\d{2})\b", re.I)
_WEATHER = [
    ("rain", re.compile(r"\b(rain|raining|rainy|rainfall|downpour|drizzle|monsoon|flood|flooded|flooding|waterlogged|"
                        r"deluge|thunderstorm|cloudburst)\b|बारिश|बरसात|बाढ़|मानसून|भारी बारिश|जलभराव")),
    ("sunny", re.compile(r"\b(sunny|sunshine|heatwave|heat wave|scorching|clear sky|bright day)\b|धूप|चिलचिलाती|लू")),
    ("fog", re.compile(r"\b(fog|foggy|mist|misty|smog)\b|कोहरा|धुंध")),
    ("snow", re.compile(r"\b(snow|snowfall|snowy|blizzard)\b|बर्फ|बर्फबारी")),
]
_OPPOSITE = {("rain", "sunny"), ("sunny", "rain"), ("sunny", "snow"), ("snow", "sunny"), ("fog", "sunny"),
             ("sunny", "fog")}


@dataclass
class Claims:
    places: list = field(default_factory=list)       # canonical names, specific (city) first
    time_kind: str | None = None                     # 'recent' | 'year'
    year: int | None = None
    time_phrase: str | None = None
    weather: str | None = None
    weather_phrase: str | None = None
    place_inherited: bool = False                    # place carried over from an earlier line of the script

    @property
    def place(self):
        return self.places[0] if self.places else None

    def any(self) -> bool:
        return bool(self.places or self.time_kind or self.weather)

    def to_dict(self):
        return {"places": self.places, "time": self.time_phrase, "year": self.year, "weather": self.weather,
                "place_inherited": self.place_inherited}


def inherit_places(claims: list) -> list:
    """Script-level context: a line that names no place is about the place named most recently before it
    ("Heavy rain lashed Mumbai." → "Commuters waited at flooded stations." is still Mumbai). Time and weather are
    line-level and are NOT inherited. Mutates and returns the list."""
    carry = None
    for c in claims:
        if c.places:
            carry = list(c.places)
        elif carry:
            c.places, c.place_inherited = list(carry), True
    return claims


def extract_claims(text: str) -> Claims:
    c = Claims()
    by = _gaz()[0]
    rank = {"city": 0, "region": 1, "country": 2}
    mentions = match_places(text)
    c.places = [n for n, _ in sorted(mentions, key=lambda m: rank.get(by[m[0]].get("kind"), 3))]
    ym = _YEAR.search(text or "")
    if ym:
        c.time_kind, c.year, c.time_phrase = "year", int(ym.group(1)), ym.group(1)
    else:
        rm = _RECENT.search((text or "").lower())
        if rm:
            c.time_kind, c.time_phrase = "recent", rm.group(0)
    low = (text or "").lower()
    for w, rx in _WEATHER:
        m = rx.search(low)
        if m:
            c.weather, c.weather_phrase = w, m.group(0)
            break
    return c


# ───────────────────────────── evidence ─────────────────────────────
def parse_partial_date(s):
    """'2019-08-10T..' | '2019-08' | '2019' -> (lo: date, hi: date) bounds of what we know, or None."""
    if not s:
        return None
    m = re.match(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", str(s))
    if not m:
        return None
    y = int(m.group(1))
    try:
        if m.group(3):
            d = date(y, int(m.group(2)), int(m.group(3)))
            return d, d
        if m.group(2):
            mo = int(m.group(2))
            lo = date(y, mo, 1)
            hi = (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1))
            return lo, hi
        return date(y, 1, 1), date(y, 12, 31)
    except ValueError:
        return None


def place_evidence(f: dict) -> list:
    """Hard-ish evidence of where the shot is. Strongest first: GPS > signboard OCR > stock title/tags."""
    ev = []
    if f.get("gps_lat") is not None and f.get("gps_lon") is not None:
        nc = nearest_city(f["gps_lat"], f["gps_lon"])
        if nc:
            ev.append({"name": nc[0], "src": "gps", "text": f"GPS {nc[1]:.0f} km from {nc[0]}"})
    if f.get("ocr_text"):
        for n, al in match_places(f["ocr_text"]):
            ev.append({"name": n, "src": "ocr", "text": f'signboard text "{f["ocr_text"][:60]}"'})
    meta = ", ".join(x for x in (f.get("title"), f.get("tags")) if x)
    if meta:
        for n, al in match_places(meta):
            ev.append({"name": n, "src": "meta", "text": f'title/tags "{(f.get("title") or meta)[:60]}"'})
    return ev


# ───────────────────────────── verdict ─────────────────────────────
STATUS_RANK = {"ok": 0, "unverified": 1, "warn": 2, "bad": 3}


@dataclass
class Verdict:
    status: str
    checks: dict
    evidence: list
    label: str | None
    delta: float

    def to_dict(self):
        return {"status": self.status, "checks": self.checks, "evidence": self.evidence,
                "label": self.label, "delta": round(self.delta, 4)}


def _check_place(claims: Claims, f: dict):
    """Evidence INSIDE a claimed place confirms it (Mumbai evidence confirms 'Mumbai' and 'Maharashtra').
    Evidence that is unrelated to EVERY claimed place contradicts it. Coarser evidence (India for Mumbai) is neutral."""
    wants = claims.places
    if not wants:
        return None
    ctx = " (place carried over from earlier in the script)" if claims.place_inherited else ""
    ev = place_evidence(f)
    confirm = [e for e in ev if any(is_within(e["name"], w) for w in wants)]
    if confirm:
        e = confirm[0]
        return "ok", f'Place confirmed: {e["name"]} ({e["text"]})'
    clash = [e for e in ev if not any(related(e["name"], w) for w in wants)]
    if clash:
        city = [e for e in clash if entry(e["name"]).get("kind") != "country"]
        e = (city or clash)[0]
        return "bad", f'Shows {e["name"]} ({e["text"]}), but the narration says {" / ".join(wants[:2])}{ctx}'
    if ev:
        return "unverified", f'Only coarse evidence ({ev[0]["name"]}); cannot confirm {wants[0]}'
    return "unverified", f"No place evidence in the footage to confirm {wants[0]}"


def _check_time(claims: Claims, f: dict, today: date):
    if not claims.time_kind:
        return None, None
    rng = parse_partial_date(f.get("shot_date"))
    src = f.get("date_source") or "unknown"
    reliable = src in ("meta", "recorded") and rng
    upper_only = src == "upload" and rng             # recording is on or before the upload date
    if claims.time_kind == "year":
        y = claims.year
        if reliable:
            if rng[0].year <= y <= rng[1].year:
                return ("ok", f"Recorded {f['shot_date'][:10]} matches the narration's {y}"), None
            return ("bad", f"Recorded {f['shot_date'][:10]}, but the narration says {y}"), None
        if upper_only and y > rng[1].year:
            return ("bad", f"Uploaded {f['shot_date'][:10]}, so it cannot be from {y}"), None
        return ("unverified", f"Recording date unknown; cannot confirm {y}"), None
    # recent
    limit = today - timedelta(days=RECENT_DAYS)
    if reliable:
        if rng[1] < limit:
            return ("warn", f'Recorded {f["shot_date"][:10]}, narration says "{claims.time_phrase}"'), f"FILE · {rng[1].year}"
        if rng[0] >= limit:
            return ("ok", f"Recorded {f['shot_date'][:10]}, recent"), None
        return ("unverified", f"Recorded around {f['shot_date'][:10]}; cannot confirm it is recent"), None
    if upper_only and rng[1] < limit:
        return ("warn", f'Uploaded {f["shot_date"][:10]}, so it is older than "{claims.time_phrase}"'), f"FILE · {rng[1].year}"
    return ("unverified", "Recording date unknown; cannot confirm it is recent"), None


def _check_weather(claims: Claims, f: dict):
    if not claims.weather:
        return None
    t, conf = f.get("weather"), f.get("weather_conf") or 0.0
    if t is None or t in ("night", "cloudy", "indoor"):
        return "unverified", "Weather not determinable from the footage"
    if (claims.weather, t) in _OPPOSITE:
        if conf >= WEATHER_BAD_CONF:
            return "bad", f'Footage looks {t} (confidence {conf:.2f}), but the narration says {claims.weather_phrase}'
        if conf >= WEATHER_WARN_CONF:
            return "warn", f'Footage may look {t} (confidence {conf:.2f}) while the narration says {claims.weather_phrase}'
        return "unverified", "Weather unclear"
    if t == claims.weather and conf >= 0.60:
        return "ok", f"Footage looks {t} (confidence {conf:.2f})"
    return "unverified", "Weather unclear"


def verdict(claims: Claims, f: dict, today: date | None = None) -> Verdict:
    today = today or date.today()
    checks, ev, label = {}, [], None

    pl = _check_place(claims, f)
    if pl:
        checks["place"] = {"status": pl[0], "evidence": pl[1]}
    tm, tlabel = _check_time(claims, f, today)
    if tm:
        checks["time"] = {"status": tm[0], "evidence": tm[1]}
        label = tlabel
    wx = _check_weather(claims, f)
    if wx:
        checks["weather"] = {"status": wx[0], "evidence": wx[1]}

    # stock-as-news: a specific PLACE claim illustrated by generic stock that has no place evidence
    is_stock = (f.get("source") or "own") != "own"
    if is_stock and claims.place and not claims.place_inherited and checks["place"]["status"] == "unverified":
        checks["stock"] = {"status": "warn", "evidence": f'Stock footage ({f.get("source")}), not footage of the '
                           f'actual event in {claims.place}'}
        label = label or "STOCK · not event footage"

    if not checks:
        return Verdict("unverified", {}, [], None, 0.0)

    statuses = [c["status"] for c in checks.values()]
    status = ("bad" if "bad" in statuses else "warn" if "warn" in statuses
              else "ok" if "ok" in statuses else "unverified")
    strong = {"place"} | ({"time"} if claims.time_kind == "year" else set())   # an explicit year match is as strong as a place match
    pos = sum(DELTA_OK_PLACE if k in strong else DELTA_OK_OTHER for k, c in checks.items() if c["status"] == "ok")
    neg = sum(DELTA_WARN for c in checks.values() if c["status"] == "warn")
    delta = min(pos, DELTA_CAP) + neg
    order = sorted(checks.values(), key=lambda c: -STATUS_RANK[c["status"]])
    ev = [c["evidence"] for c in order if c["status"] != "unverified"] or [c["evidence"] for c in order]
    return Verdict(status, checks, ev, label, delta)


# ───────────────────────────── DB glue ─────────────────────────────
def fetch_facts(shot_ids) -> dict:
    ids = [int(i) for i in shot_ids]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    rows = db.conn().execute(
        f"""SELECT s.id, s.weather, s.weather_conf, p.shot_date, p.date_source, p.source_kind, p.ocr_text,
                   p.gps_lat, p.gps_lon, si.title, si.tags, si.source
            FROM shots s LEFT JOIN provenance p ON p.shot_id=s.id LEFT JOIN stock_items si ON si.id=s.stock_id
            WHERE s.id IN ({q})""", ids).fetchall()
    out = {}
    for r in rows:
        d = dict(r)
        d["source"] = d.get("source") or "own"
        out[d["id"]] = d
    return out


def backfill_weather_conf(batch=2000, force=False):
    """Recompute weather label + confidence from stored embeddings (new shots, or everything with force=True
    after the prompt set changes)."""
    import numpy as np
    from . import store
    from .indexer import tags
    c = db.conn()
    where = "emb_row IS NOT NULL" + ("" if force else " AND weather_conf IS NULL")
    rows = c.execute(f"SELECT id, emb_row FROM shots WHERE {where}").fetchall()
    if not rows:
        return 0
    M = store.load_matrix()
    n = 0
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        E = M[[r["emb_row"] for r in part]]
        labels, confs = tags.zero_shot(E, "weather")
        c.executemany("UPDATE shots SET weather=?, weather_conf=? WHERE id=?",
                      [(l, cf, r["id"]) for l, cf, r in zip(labels, confs, part)])
        c.commit()
        n += len(part)
    return n


if __name__ == "__main__":
    import sys
    if "--backfill" in sys.argv:
        print("weather_conf backfilled for", backfill_weather_conf(force="--force" in sys.argv), "shots")
