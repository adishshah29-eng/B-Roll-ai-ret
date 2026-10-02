from ..config import PIXABAY_API_KEY
from .base import Connector, StockItem, fetch_json

URL = "https://pixabay.com/api/videos/"


class Pixabay(Connector):
    name = "pixabay"
    max_pages = 5                 # the API caps every query at 500 hits → 5 × 100

    def search(self, query, page):
        if not PIXABAY_API_KEY:
            return []
        d = fetch_json("pixabay", URL, {"key": PIXABAY_API_KEY, "q": query, "per_page": 100, "page": page,
                                        "safesearch": "true"})
        out = []
        for h in d.get("hits", []):
            if h.get("isAiGenerated") or h.get("isLowQuality"):      # we only want real footage
                continue
            v = h.get("videos", {})
            tiny = v.get("tiny") or v.get("small") or {}
            if not tiny.get("thumbnail") or (h.get("duration") or 0) < 2:
                continue
            tags = h.get("tags", "")
            rend = {k: {"url": x["url"], "w": x["width"], "h": x["height"], "size": x["size"]}
                    for k, x in v.items() if x.get("url")}
            out.append(StockItem(
                source="pixabay", source_id=str(h["id"]), title=", ".join(tags.split(", ")[:3]), tags=tags,
                author=h.get("user", ""), author_url=h.get("userURL", ""), page_url=h.get("pageURL", ""),
                licence="Pixabay Content License", licence_url="https://pixabay.com/service/license-summary/",
                date_kind="unknown", duration=float(h.get("duration") or 0),
                width=tiny.get("width"), height=tiny.get("height"),
                preview_url=tiny["thumbnail"], renditions=rend))
        return out
