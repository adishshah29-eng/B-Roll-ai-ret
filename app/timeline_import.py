"""Parse timelines (FCP7 XML / xmeml and CMX3600 EDL) into placements.
Used by Edit Memory (P7) to learn which shots an editor put under which narration, and by audit mode."""
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote

FPS_DEFAULT = 25


def _path_from_url(u: str) -> str:
    u = unquote(u or "")
    u = re.sub(r"^file://(localhost)?/?", "", u)
    return u.replace("/", "\\") if re.match(r"^[A-Za-z]:", u) else "/" + u.lstrip("/")


def parse_xmeml(text: str) -> list:
    root = ET.fromstring(text)
    seq_rate = int(root.findtext(".//sequence/rate/timebase") or FPS_DEFAULT)
    files = {}
    for f in root.iter("file"):
        if f.get("id") and f.findtext("pathurl"):
            files[f.get("id")] = _path_from_url(f.findtext("pathurl"))
    out = []
    for ci in root.iter("clipitem"):
        f = ci.find("file")
        path = files.get(f.get("id")) if f is not None else None
        if not path:
            continue
        rate = int(ci.findtext("rate/timebase") or seq_rate)
        a, b = int(ci.findtext("in") or 0), int(ci.findtext("out") or 0)
        s, e = int(ci.findtext("start") or 0), int(ci.findtext("end") or 0)
        out.append({"path": path, "name": ci.findtext("name") or "", "src_in": a / rate, "src_out": b / rate,
                    "rec_in": s / seq_rate, "rec_out": e / seq_rate,
                    "note": ci.findtext("comments/mastercomment1") or ""})
    return sorted(out, key=lambda c: c["rec_in"])


_TC = r"(\d\d):(\d\d):(\d\d)[:;](\d\d)"


def _tc(h, m, s, f, fps=FPS_DEFAULT):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(f) / fps


def parse_edl(text: str, fps=FPS_DEFAULT) -> list:
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(rf"^\s*(\d+)\s+(\S+)\s+V\s+C\s+{_TC}\s+{_TC}\s+{_TC}\s+{_TC}", line)
        if m:
            g = m.groups()
            cur = {"reel": g[1], "path": None, "name": "",
                   "src_in": _tc(*g[2:6], fps), "src_out": _tc(*g[6:10], fps),
                   "rec_in": _tc(*g[10:14], fps), "rec_out": _tc(*g[14:18], fps), "note": ""}
            out.append(cur)
        elif cur and line.startswith("* FROM CLIP NAME:"):
            cur["name"] = line.split(":", 1)[1].strip()
        elif cur and line.startswith("* COMMENT:"):
            cur["note"] = line.split(":", 1)[1].strip()
    return out


def parse(path_or_text: str, kind: str | None = None) -> list:
    text = path_or_text
    if "\n" not in path_or_text and len(path_or_text) < 1024:
        try:
            text = open(path_or_text, encoding="utf-8").read()
        except OSError:
            pass
    kind = kind or ("xml" if text.lstrip().startswith("<") else "edl")
    return parse_xmeml(text) if kind == "xml" else parse_edl(text)
