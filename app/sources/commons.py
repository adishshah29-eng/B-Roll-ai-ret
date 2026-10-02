import re

from .base import Connector, StockItem, fetch_json

API = "https://commons.wikimedia.org/w/api.php"
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}


def parse_date(s):
    """'29 April 2020 at 1:16 pm' | '2020-04-29' | 'April 2020' | '2020' → ISO (day/month may be missing)."""
    if not s:
        return None
    s = re.sub(r"<[^>]+>", " ", str(s)).strip().lower()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", s)
    if m and m.group(2) in _MONTHS:
        return f"{m.group(3)}-{_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"([a-z]+)\s+(\d{4})", s)
    if m and m.group(1) in _MONTHS:
        return f"{m.group(2)}-{_MONTHS[m.group(1)]:02d}"
    m = re.search(r"\b(?:19|20)\d{2}\b", s)
    return m.group(0) if m else None


def _txt(x):
    return re.sub(r"<[^>]+>", "", x or "").strip()


class Commons(Connector):
    name = "commons"
    max_pages = 4

    def search(self, query, page):
        d = fetch_json("commons", API, {
            "action": "query", "generator": "search", "gsrsearch": f"{query} filetype:video",
            "gsrnamespace": 6, "gsrlimit": 50, "gsroffset": (page - 1) * 50,
            "prop": "imageinfo|coordinates", "iiprop": "url|size|mime|timestamp|extmetadata|mediatype",
            "iiurlwidth": 640, "colimit": 50, "format": "json", "formatversion": 2})
        out = []
        for p in (d.get("query", {}).get("pages") or []):
            ii = (p.get("imageinfo") or [None])[0]
            if not ii or not ii.get("thumburl") or (ii.get("duration") or 0) < 2:
                continue
            em = ii.get("extmetadata", {})
            orig = parse_date(em.get("DateTimeOriginal", {}).get("value"))
            up = parse_date(ii.get("timestamp"))
            coords = (p.get("coordinates") or [None])[0]
            title = p["title"].removeprefix("File:").rsplit(".", 1)[0]
            out.append(StockItem(
                source="commons", source_id=str(p["pageid"]), title=title,
                tags=_txt(em.get("Categories", {}).get("value", "")).replace("|", ", "),
                author=_txt(em.get("Artist", {}).get("value", ""))[:80],
                page_url=ii.get("descriptionurl", ""),
                licence=em.get("LicenseShortName", {}).get("value", ""),
                licence_url=em.get("LicenseUrl", {}).get("value", ""),
                published_at=orig or up, date_kind="recorded" if orig else "upload",
                gps=(coords["lat"], coords["lon"]) if coords else None,
                duration=float(ii["duration"]), width=ii.get("width"), height=ii.get("height"),
                preview_url=ii["thumburl"],
                renditions={"original": {"url": ii["url"], "size": ii.get("size", 0), "mime": ii.get("mime")}}))
        return out
