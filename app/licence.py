"""Licence classification: can this clip go into a commercial video / ad?

Classes
  own          your own footage
  safe         public domain, CC0, or a free-to-use stock licence (no credit required)
  attribution  CC BY: commercial use allowed, credit required (the export generates the credit text)
  caution      CC BY-SA: commercial use allowed but share-alike; not treated as ad-safe by default
  restricted   any NonCommercial or NoDerivatives licence: must not be used in commercial videos / ads
  unknown      no licence information: not treated as safe

`commercial=True` classes (own, safe, attribution) pass the "commercial-safe only" filter.
This is a practical triage of the licence text we stored, not legal advice: always check the source page for a clip you rely on.
"""
LABELS = {
    "own": "Your footage",
    "safe": "Free to use",
    "attribution": "Credit required",
    "caution": "Share-alike",
    "restricted": "Non-commercial",
    "unknown": "Licence unknown",
}
COMMERCIAL = ("own", "safe", "attribution")


def classify(licence, licence_url=None, source=None) -> str:
    if not source or source == "own":
        return "own"
    s = f"{licence or ''} {licence_url or ''}".lower()
    if not s.strip():
        return "unknown"
    if "-nc" in s or "noncommercial" in s or "non-commercial" in s or "-nd" in s or "noderiv" in s:
        return "restricted"
    if any(k in s for k in ("public domain", "publicdomain", "cc0", "zero/1.0", "mark/1.0", "pixabay")):
        return "safe"
    if "-sa" in s or "sharealike" in s or "share-alike" in s:
        return "caution"
    if "cc by" in s or "cc-by" in s or "/licenses/by/" in s:
        return "attribution"
    return "unknown"


def is_commercial(cls: str) -> bool:
    return cls in COMMERCIAL


def attribution_text(title, author, licence, url, page_url) -> str:
    """Ready-to-paste credit line for clips whose licence asks for one."""
    who = f" by {author}" if author else ""
    lic = (licence or "").strip()
    if lic.startswith("http"):
        lic = "Creative Commons licence"
    link = page_url or url or ""
    return f"“{title}”{who}. {lic}. {link}".strip()
