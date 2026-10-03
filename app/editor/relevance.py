"""Strict relevance for the Script page: a shot is only shown if a picture check confirms it fits its line AND the script's topic.

planner.plan (CLIP relevance + TRUE + CUTS + YOURS) proposes shots. This module then
  1. drops clips whose own title names a place unrelated to the script,
  2. has Gemini LOOK at each beat's candidate pictures (with the script's topic as context) and keeps only the confirmed ones,
  3. for beats where nothing fits, fetches topic-specific clips from Pixabay once and tries again,
  4. leaves a beat EMPTY (with the reason) rather than show an irrelevant clip.
Without a Gemini key only step 1 can run, and the response says the pictures were not checked.
"""
from .. import db, truth
from ..planner import Beat, plan as plan_beats
from . import judge, live, llm, suggest

SCRIPT_LIB = "Fetched for scripts"
MAX_RESCUE_QUERIES = 10


def script_live_library() -> int:
    """One shared 'live' library for clips fetched on behalf of scripts (hidden from 'All footage', used via also_lib)."""
    c = db.conn()
    r = c.execute("SELECT id FROM libraries WHERE name=?", (SCRIPT_LIB,)).fetchone()
    if r:
        return r["id"]
    lid = c.execute("INSERT INTO libraries(name, domain, kind) VALUES(?,?,?)",
                    (SCRIPT_LIB, "clips fetched live while planning scripts", "live")).lastrowid
    c.commit()
    return lid


def topic_of(script: str) -> tuple:
    places = []
    for n, _ in truth.match_places(script):
        if n not in places:
            places.append(n)
    kws = [w for w in llm.keywords(script, n=10).split() if w.lower() not in suggest.FILLER]
    words = []
    for w in places[:3] + kws:
        if w.lower() not in [x.lower() for x in words]:
            words.append(w)
    return " ".join(words[:6]), places


def _slots(beats: list, vplaces: list, idx=None) -> list:
    out = []
    for k, b in enumerate(beats):
        if idx is not None and k not in idx:
            out.append({"text": b["text"], "query": "", "shot": None, "alts": []})
            continue
        pool, seen = [], set()
        for c in (b.get("chosen") or []) + (b.get("alts") or []):       # the planner's picks first
            if c["id"] in seen or suggest.wrong_place(c, vplaces):
                continue
            seen.add(c["id"])
            pool.append(c)
        out.append({"text": b["text"], "query": llm.keywords(b["text"], n=4), "shot": None, "alts": pool})
    return out


def _apply(beats: list, slots: list, idx=None):
    """Keep only picture-confirmed clips; mark beats where nothing fits."""
    for k, (b, s) in enumerate(zip(beats, slots)):
        if idx is not None and k not in idx:
            continue
        j = s.get("judge")
        if not j or j.get("good_ids") is None:
            b["relevance"] = {"checked": False}
            continue
        ids = j["good_ids"]
        pool = {c["id"]: c for c in s.get("alts", [])}
        if s.get("shot"):
            pool[s["shot"]["id"]] = s["shot"]
        keep = [c for c in (b.get("chosen") or []) if c["id"] in ids]
        want = max(1, len(b.get("chosen") or []))
        for gid in ids:
            if len(keep) >= want:
                break
            if gid in pool and all(x["id"] != gid for x in keep):
                keep.append(pool[gid])
        b["chosen"] = keep
        b["alts"] = [c for cid, c in pool.items() if cid in ids and all(x["id"] != cid for x in keep)]
        b["relevance"] = {"checked": True, "fit": len(ids), "of": j.get("of"), "reason": j.get("reason", ""), "queries": j.get("queries") or []}
        b["no_match"] = not keep


def filter_plan(searcher, out: dict, script: str, req) -> dict:
    beats = out.get("beats") or []
    if not beats:
        return out
    topic, vplaces = topic_of(script)
    ctx = f"{topic} (script: {script.strip()[:200]})" if topic else script.strip()[:200]
    slots = _slots(beats, vplaces)
    res = judge.check_many(slots, context=ctx)
    summary = {"strict": True, "checked": bool(res.get("ok")), "topic": topic, "rescued": 0, "unmatched": 0, "error": res.get("error")}
    if not res.get("ok"):                                               # no Gemini: only the wrong-place rule could run
        for b, s in zip(beats, slots):
            ok = {c["id"] for c in s["alts"]}
            b["chosen"] = [c for c in b.get("chosen", []) if c["id"] in ok]
            b["alts"] = [c for c in b.get("alts", []) if c["id"] in ok]
            b["relevance"] = {"checked": False}
        out["relevance"] = {**summary, "reason": "Gemini is not available, so the pictures were not checked (only wrong-place clips were removed)."}
        return _finish(out)
    _apply(beats, slots)

    need = [i for i, b in enumerate(beats) if b.get("no_match")]
    if need:                                                            # nothing fit: fetch topic-specific clips once, then re-check
        qs = []
        for n, i in enumerate(need):
            qs += (beats[i]["relevance"].get("queries") or [])[:2]
            qs += judge.topic_queries("", topic, beats[i]["text"], n=2) if n < 4 else [f"{llm.keywords(beats[i]['text'], n=4)} {topic}".strip()]
        qs = list(dict.fromkeys(q for q in qs if q))[:MAX_RESCUE_QUERIES]
        lib = getattr(req, "library", None)
        lid = lib or script_live_library()
        if qs:
            live.fetch(qs, searcher, None, library_id=lid, n_main=len(qs))
            sub = [Beat(i, beats[i]["text"], beats[i]["dur"], None) for i in need]
            p2 = plan_beats(searcher, "", beats=sub, use_truth=getattr(req, "use_truth", True), today=getattr(req, "today", None),
                            use_cuts=False, use_memory=getattr(req, "use_memory", True), library=lib, also_lib=None if lib else lid)
            for b2 in p2.get("beats", []):
                b = beats[b2["i"]]
                b["chosen"], b["alts"], b["rejected"], b["n_rejected"] = b2["chosen"], b2["alts"], b2["rejected"], b2["n_rejected"]
            # widen the pool for the empty beats: topic-specific searches over the library (incl. what was just fetched)
            pseudo = {"library": lib, "live_library": None if lib else lid}
            per_beat = {i: list(dict.fromkeys([beats[i]["text"], f"{llm.keywords(beats[i]['text'], n=4)} {topic}".strip(), *qs]))[:5] for i in need}
            for i in need:
                have = {c["id"] for c in (beats[i].get("chosen") or []) + (beats[i].get("alts") or [])}
                extra = [c for c in suggest.candidates(searcher, pseudo, per_beat[i], 20) if c["id"] not in have]
                beats[i]["alts"] = (beats[i].get("alts") or []) + extra
            idx = set(need)
            slots2 = _slots(beats, vplaces, idx)
            judge.check_many([slots2[i] for i in need], per_slot=judge.PER_SLOT_RETRY, context=ctx)
            _apply(beats, slots2, idx)
            summary["rescued"] = sum(1 for i in need if beats[i].get("chosen"))
    summary["unmatched"] = sum(1 for b in beats if b.get("no_match"))
    out["relevance"] = summary
    return _finish(out)


def _finish(out: dict) -> dict:
    """The licence summary must describe what is actually shown now."""
    counts, unsafe = {}, []
    for b in out["beats"]:
        for c in b.get("chosen", []):
            counts[c["licence"]["class"]] = counts.get(c["licence"]["class"], 0) + 1
            if not c["licence"]["commercial"]:
                unsafe.append({"beat": b["i"], "file": c["file"], "class": c["licence"]["class"], "label": c["licence"]["label"]})
    out["licences"] = {**(out.get("licences") or {}), "counts": counts, "unsafe": unsafe, "commercial_ok": not unsafe}
    return out
