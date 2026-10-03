"""Second opinion on the picks: Gemini LOOKS at the candidate thumbnails for each spot and says which ones really show what the
narration is about.

CLIP scores of a text against one thumbnail are too flat to separate "code on a screen" from "something techy" (every candidate sat
between 0.29 and 0.32), so relevance alone let a Matrix rain clip through for "AI and web dev". A vision model that sees the
picture and the sentence together does not have that problem. One request covers the whole project (all spots, a few thumbnails
each), so it costs one call. Without a key, or if the call fails, the picks are left exactly as the retrieval chose them.
"""
import base64

from .. import gemini
from ..config import THUMBS

PER_SLOT = 8            # candidates shown per spot on the first pass
PER_SLOT_RETRY = 12     # ...and after a rewritten search
MAX_IMAGES = 60


def _thumb(shot_id: int) -> bytes | None:
    p = THUMBS / f"{shot_id}.jpg"
    return p.read_bytes() if p.exists() else None


def _candidates(slot: dict, n: int = PER_SLOT) -> list:
    seen, out = set(), []
    for sh in [slot.get("shot"), slot.get("suggested"), *(slot.get("alts") or [])]:
        if sh and sh.get("id") not in seen:
            seen.add(sh["id"])
            out.append(sh)
    return out[:n]


PROMPT = """You are checking B-roll for a video editor. For each SPOT you get the narration (what the speaker says) and the search
that was used, then numbered candidate pictures. Say which candidates would genuinely be good B-roll for that narration:
the picture must show what is being talked about (the real subject, not just something with the same mood or a similar word).
A candidate FITS if it clearly shows the main subject or action of the line, or something that naturally goes with it in the same setting, and nothing about it is wrong for the topic or place. It does NOT need to show every detail the line mentions (a bowl of pasta being served fits \"plates a bowl of pasta\" even without a chef or basil in frame). 
Reject: sci-fi/neon/CGI imagery when the topic is real-world, green-screen or animated intro/subscribe templates, pictures of a
different subject that merely shares a keyword, and anything unrelated.
If the narration names a place (a city, state or region), reject pictures that clearly show a DIFFERENT place or region: for example
Himalayan monasteries or snow peaks do not fit a line about Rajasthan's palaces, and a Mumbai street does not fit Delhi. Use any
visible landmark, architecture, landscape, script on signs or the clip's own look; when you cannot tell, prefer candidates that look
right for that place.

If NO candidate for a spot is good, also give "queries": 3 new stock-site searches for that spot (2-4 plain English words about ONE
concrete, filmable subject, different from the search used, based on what was missing; prefer real footage over abstract/CGI imagery;
never use the words: {banned}).

Return JSON only: {{"spots": [{{"spot": int, "good": [candidate numbers, best first, [] if none is good], "reason": "one short sentence", "queries": [str, str, str] (only when good is [])}}]}}
"""


def check(slots: list, per_slot: int = PER_SLOT, context: str = "") -> dict | None:
    """Annotate `slots` in place with `judge` and re-order/replace picks. Returns a small status dict, or None if skipped."""
    if not gemini.enabled():
        return None
    from . import llm
    head = PROMPT.format(banned=", ".join(llm.BANNED))
    if context:
        head += f"\nThe whole video / script is about: {context}. A candidate must also fit that topic and place, not only the single line.\n"
    parts, index, n_img = [{"text": head}], {}, 0
    for i, s in enumerate(slots):
        if s.get("locked"):
            continue
        cands = [c for c in _candidates(s, per_slot) if n_img + 1 <= MAX_IMAGES]
        imgs = [(c, _thumb(c["id"])) for c in cands]
        imgs = [(c, b) for c, b in imgs if b]
        if not imgs:
            continue
        index[i] = [c for c, _ in imgs]
        parts.append({"text": f"\nSPOT {i}: narration: \"{(s.get('text') or '')[:200]}\" | search: \"{s.get('query', '')}\""})
        for k, (c, b) in enumerate(imgs, 1):
            parts += [{"text": f"candidate {k}:"}, {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(b).decode()}}]
            n_img += 1
    if not index:
        return None
    try:
        data = gemini.generate_json("", temperature=0.1, timeout=90, parts=parts)
    except Exception as e:                      # never block the edit
        return {"ok": False, "error": gemini.redact(e)}
    changed = 0
    for r in data.get("spots", []):
        try:
            i = int(r["spot"])
            good = [int(g) for g in r.get("good", [])]
        except (KeyError, TypeError, ValueError):
            continue
        if i not in index:
            continue
        cands, s = index[i], slots[i]
        ok = [cands[g - 1] for g in good if 1 <= g <= len(cands)]
        rest = [c for c in cands if c not in ok]
        s["judge"] = {"by": "gemini", "good": len(ok), "of": len(cands), "reason": str(r.get("reason", ""))[:160],
                      "good_ids": [c["id"] for c in ok]}
        if not ok and r.get("queries"):
            s["judge"]["queries"] = [llm.clean_query(q) for q in r["queries"] if str(q).strip()][:3]
        s["alts"] = ok[1:] + rest + [a for a in (s.get("alts") or []) if a.get("id") not in {c["id"] for c in cands}]
        s["alts"] = s["alts"][:12]
        cur = s.get("shot") or s.get("suggested")
        if ok:
            if not cur or cur["id"] != ok[0]["id"]:
                changed += 1
            s["shot"] = ok[0]
            s.pop("suggested", None)
        elif s.get("shot"):                     # nothing shown is on topic: leave the spot empty rather than show the wrong thing
            s["suggested"], s["shot"] = s["shot"], None
            changed += 1
    return {"ok": True, "changed": changed, "spots": len(index), "images": n_img}


REWRITE = """A video editor searched a stock-footage site for B-roll and a reviewer rejected every picture that came back.
For each SPOT you get the narration, the searches already tried, and the reviewer's reason. Write 3 NEW searches per spot, each
different from those tried: 2-4 plain English words about ONE concrete, filmable subject, the way you would type them on a stock
site. Use what the reviewer said was missing. Prefer real footage (people, hands, objects, places, actions) over abstract or CGI
imagery. Never use these words: {banned}.
Return JSON only: {{"spots": [{{"spot": int, "queries": [str, str, str]}}]}}
"""


def rewrite_queries(slots: dict) -> dict:
    """slots: {index: slot} of spots the reviewer rejected. Returns {index: [new queries]} from ONE Gemini call."""
    from . import llm
    if not slots or not gemini.enabled():
        return {}
    lines = [REWRITE.format(banned=", ".join(llm.BANNED))]
    for i, s in slots.items():
        tried = [s.get("query"), *(s.get("alt_queries") or [])]
        lines.append(f'SPOT {i}: narration: "{(s.get("text") or "")[:200]}" | tried: {[t for t in tried if t]} | '
                     f'reviewer: "{(s.get("judge") or {}).get("reason", "")}"')
    try:
        data = gemini.generate_json(chr(10).join(lines), temperature=0.6, timeout=60)
    except Exception:
        return {}
    out = {}
    for r in data.get("spots", []):
        try:
            i = int(r["spot"])
        except (KeyError, TypeError, ValueError):
            continue
        qs = [llm.clean_query(q) for q in (r.get("queries") or [])]
        qs = [q for q in dict.fromkeys(qs) if q and q.lower() not in {t.lower() for t in [slots[i].get("query") or "", *(slots[i].get("alt_queries") or [])]}] if i in slots else []
        if qs:
            out[i] = qs[:3]
    return out


def check_many(slots: list, per_slot: int = PER_SLOT, context: str = "", chunk: int = 6) -> dict:
    """judge.check in chunks (one request holds at most MAX_IMAGES pictures) so long scripts are fully covered.
    Returns {"ok": bool, "checked": number of slots that were judged}."""
    if not gemini.enabled():
        return {"ok": False, "checked": 0, "error": "no Gemini key"}
    checked, err = 0, None
    for i in range(0, len(slots), chunk):
        part = slots[i:i + chunk]
        r = check(part, per_slot, context)
        if r and r.get("ok"):
            checked += sum(1 for x in part if x.get("judge"))
        elif r:
            err = r.get("error")
    return {"ok": checked > 0, "checked": checked, "error": err}


TOPIC_Q = """A video editor needs stock footage for one spoken line of a video.
The video is about: {summary}
Topic words: {topic}
The line: "{text}"
Write {n} different stock-footage searches that would show THIS line in the context of THIS video. Each is 2-4 plain English words about
ONE concrete, filmable subject (people, hands, objects, places, actions), real footage rather than abstract or CGI imagery, and keeps
the video's place or subject (do not drift to another city or topic). Vary the angle between them. Never use these words: {banned}.
Return JSON only: {{"queries": [str, ...]}}"""


def topic_queries(summary: str, topic: str, text: str, n: int = 4) -> list:
    """Searches for a line pinned to the video's topic. Gemini writes them; without it, the line's keywords + the topic words."""
    from . import llm
    base = f"{llm.keywords(text, n=4)} {topic}".strip()
    if gemini.enabled():
        try:
            d = gemini.generate_json(TOPIC_Q.format(summary=summary or "(not available)", topic=topic or "(none)", text=(text or "")[:240],
                                                    n=n, banned=", ".join(llm.BANNED)), temperature=0.5, timeout=60)
            qs = [llm.clean_query(q) for q in (d.get("queries") or []) if str(q).strip()]
            qs = list(dict.fromkeys(q for q in qs if q))[:n]
            if qs:
                return qs + ([base] if base and base.lower() not in [q.lower() for q in qs] else [])
        except Exception:
            pass
    return [base] if base else []
