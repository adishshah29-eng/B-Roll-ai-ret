from .base import Connector, StockItem, fetch_json
from .commons import parse_date

URL = "https://archive.org/advancedsearch.php"
MAX_HYDRATE_BYTES = 300 << 20


class Archive(Connector):
    name = "archive"
    max_pages = 3

    def search(self, query, page):
        # title/subject only: a bare full-text query matches anything that mentions the word in its description
        q = (f"(title:({query}) OR subject:({query})) AND mediatype:movies "
             f"AND (licenseurl:* OR collection:prelinger) AND -identifier:youtube-*")
        d = fetch_json("archive", URL, {
            "q": q, "rows": 100, "page": page, "output": "json",
            "fl[]": ["identifier", "title", "date", "creator", "licenseurl", "item_size", "subject"]})
        out = []
        for x in d.get("response", {}).get("docs", []):
            ident = x["identifier"]
            creator = x.get("creator") or ""
            subj = x.get("subject") or ""
            size = int(x.get("item_size") or 0)
            out.append(StockItem(
                source="archive", source_id=ident, title=str(x.get("title") or ident)[:120],
                tags=", ".join(subj) if isinstance(subj, list) else str(subj),
                author=", ".join(creator) if isinstance(creator, list) else str(creator),
                page_url=f"https://archive.org/details/{ident}",
                licence=x.get("licenseurl") or "Public domain (Prelinger / Internet Archive)",
                licence_url=x.get("licenseurl") or "",
                published_at=parse_date(x.get("date")), date_kind="recorded" if x.get("date") else "unknown",
                preview_url=f"https://archive.org/services/img/{ident}",
                renditions={"item": {"size": size}}))
        return out
